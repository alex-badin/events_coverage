#!/usr/bin/env python3
"""Build the Events coverage dashboard inside a running Metabase.

Metabase is normally set up by clicking, which means the setup exists only on the machine
where the clicking happened. This script does the same work through Metabase's own
interface, so the dashboard can be rebuilt from scratch on any machine and lives in git as
code rather than as screenshots.

It is safe to run repeatedly: the database connection, every question and the dashboard are
matched by name and updated in place rather than duplicated.

What it will NOT do is create the Metabase admin account. Open http://localhost:3000 once
and create it yourself, so the password is yours and is never written down here.

Usage, from the repository root:
    METABASE_USER='you@example.com' METABASE_PASSWORD='...' .venv/bin/python metabase/provision.py

Optional:
    METABASE_URL       default http://localhost:3000
    DUCKDB_IN_CONTAINER default /data/events.duckdb
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

METABASE_URL = os.environ.get("METABASE_URL", "http://localhost:3000").rstrip("/")
DB_PATH_IN_CONTAINER = os.environ.get("DUCKDB_IN_CONTAINER", "/data/events.duckdb")
DB_NAME = "Events coverage warehouse"
DASHBOARD_NAME = "Events coverage"

# The published copy on this machine — the same file the container reads at
# DB_PATH_IN_CONTAINER. Only used to pick which event the dashboard opens on.
PUBLISHED_DB = Path(__file__).resolve().parent / "data" / "events.duckdb"

# Metabase lays dashboards out on a grid 24 columns wide.
GRID_WIDTH = 24


def default_event_slug() -> str:
    """The event with the most matched posts, read from the published warehouse.

    Read rather than written into this file, because the event slugs change whenever a
    matched set is rebuilt, and a stale default would leave the dashboard opening on an
    event that no longer exists — every question would come back empty with no explanation.
    """
    import duckdb

    if not PUBLISHED_DB.exists():
        raise SystemExit(
            f"{PUBLISHED_DB} is missing. Run:\n"
            "  .venv/bin/python scripts/publish_warehouse_for_metabase.py"
        )
    with duckdb.connect(str(PUBLISHED_DB), read_only=True) as con:
        row = con.execute(
            "select event_slug from main.event_overview order by matched_posts desc limit 1"
        ).fetchone()
    if not row:
        raise SystemExit(f"{PUBLISHED_DB} has no events in main.event_overview.")
    return row[0]


DEFAULT_EVENT_SLUG = default_event_slug()


class Metabase:
    """The few Metabase interface calls this script needs."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.token: str | None = None

    def call(self, method: str, path: str, body=None):
        url = f"{self.base_url}/api/{path.lstrip('/')}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("X-Metabase-Session", self.token)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:800]
            raise RuntimeError(f"{method} {path} failed: {error.code}\n{detail}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(
                f"Cannot reach Metabase at {self.base_url} ({error.reason}).\n"
                "Start it with:  zsh metabase/start.sh"
            ) from None

    def log_in(self, username: str, password: str) -> None:
        try:
            self.token = self.call(
                "POST", "session", {"username": username, "password": password}
            )["id"]
        except RuntimeError as error:
            # A wrong password is an ordinary mistake, not a crash — say so in one line
            # instead of printing a stack trace at someone.
            if "401" in str(error):
                raise SystemExit(
                    f"Metabase rejected the sign-in for {username}.\n"
                    "Use the admin account you created in the browser on first run. If you "
                    "have not created one yet, open the address above and do that first."
                ) from None
            raise

    def needs_first_run_setup(self) -> bool:
        """True while nobody has created the admin account yet."""
        return not self.call("GET", "session/properties").get("has-user-setup", False)


def wait_until_up(client: Metabase, seconds: int = 180) -> None:
    """Metabase takes a while to start; poll its health endpoint rather than guess."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if client.call("GET", "health").get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError(
        f"Metabase did not become healthy within {seconds}s. "
        "Check: docker logs events-coverage-metabase"
    )


def ensure_database(client: Metabase) -> int:
    """Create the DuckDB connection, or return the existing one."""
    listed = client.call("GET", "database")
    databases = listed["data"] if isinstance(listed, dict) else listed
    for database in databases:
        if database["name"] == DB_NAME:
            print(f"  connection already present (id {database['id']})")
            return database["id"]

    created = client.call(
        "POST",
        "database",
        {
            "name": DB_NAME,
            "engine": "duckdb",
            "details": {
                "database_file": DB_PATH_IN_CONTAINER,
                # Metabase never needs to write here, and a reporting tool that cannot write
                # to its source cannot damage it.
                "read_only": True,
            },
            "is_full_sync": True,
        },
    )
    print(f"  created connection (id {created['id']})")
    return created["id"]


def wait_for_tables(client: Metabase, database_id: int, expected: int, seconds: int = 180) -> None:
    """Metabase reads the schema in the background; wait until the marts are visible."""
    deadline = time.time() + seconds
    seen = 0
    while time.time() < deadline:
        tables = client.call("GET", f"database/{database_id}/metadata").get("tables", [])
        seen = len(tables)
        if seen >= expected:
            print(f"  {seen} tables visible")
            return
        time.sleep(3)
    raise RuntimeError(
        f"Only {seen} of {expected} tables appeared within {seconds}s. "
        "If this is a driver problem the reason is in: docker logs events-coverage-metabase"
    )


EVENT_TAG = {
    "event_slug": {
        "id": "b6c9f1a2-0e3d-4c7b-9f11-2a5d8e4c7b31",
        "name": "event_slug",
        "display-name": "Event",
        "type": "text",
        "default": DEFAULT_EVENT_SLUG,
    }
}


def card(name, description, sql, display, settings, filtered):
    return {
        "name": name,
        "description": description,
        "sql": sql,
        "display": display,
        "settings": settings,
        "filtered": filtered,
    }


CARDS = [
    card(
        "Events: public attention against coverage",
        "One row per event. The survey share is how often people named the event unprompted; "
        "the post count is how many posts matched it. Events marked with a warning were "
        "matched on settings that make their counts non-comparable with the rest.",
        """
        select
            event_name                                as "Event",
            fom_year                                  as "Year",
            fom_week                                  as "Week",
            attention_percentage                      as "Survey share %",
            matched_posts                             as "Matched posts",
            round(matched_posts_per_1000_published, 1) as "Per 1,000 published",
            sources_covering                          as "Sources covering",
            sources_active                            as "Sources publishing",
            round(searchable_share_of_window, 3)      as "Share of window searchable",
            rerank_threshold                          as "Relevance cut-off",
            case
                when not standard_relevance_cutoff then 'weaker matches let in'
                when searchable_share_of_window < 0.9 then 'part of the window not searchable'
            end                                       as "Warning"
        from event_overview
        order by attention_percentage desc
        """,
        "table", {}, False,
    ),
    card(
        "Survey share against matched posts",
        "Each event placed by how often the public named it and how many posts matched it. "
        "The two axes are different units — read the positions, not the distance between them.",
        """
        select
            event_name              as "Event",
            attention_percentage    as "Survey share %",
            matched_posts           as "Matched posts"
        from event_overview
        """,
        "scatter",
        {"graph.dimensions": ["Survey share %"], "graph.metrics": ["Matched posts"]},
        False,
    ),
    card(
        "Which events landed with which kinds of media",
        "Each number compares a media group against its own average across all loaded events, "
        "so 1.0 means exactly as usual for that group. Above 1 on 'slice of event' means the "
        "group took a bigger share of this event's coverage than it usually takes.",
        """
        select
            media_group                     as "Media group",
            event_name                      as "Event",
            matched_posts                   as "Matched posts",
            round(coverage_lift, 2)         as "Slice vs usual",
            round(effort_lift, 2)           as "Own output vs usual",
            round(audience_lift, 2)         as "Views per post vs usual",
            round(share_of_event_views, 3)  as "Share of event views",
            coverage_lift_label             as "Reading"
        from event_group_resonance
        order by coverage_lift desc nulls last
        """,
        "table", {}, False,
    ),
    card(
        "Coverage by media group",
        "Matched posts per media group for the selected event. Groups that published nothing "
        "about it appear with a zero, so silence is visible rather than missing.",
        """
        select
            media_group    as "Media group",
            matched_posts  as "Matched posts"
        from event_group_coverage
        where event_slug = {{event_slug}}
        order by matched_posts desc
        """,
        "bar",
        {"graph.dimensions": ["Media group"], "graph.metrics": ["Matched posts"]},
        True,
    ),
    card(
        "Share of a group's own output",
        "The same coverage divided by everything the group published in the window, on any "
        "topic. This is what stops the largest publishers from automatically looking the most "
        "interested.",
        """
        select
            media_group                                as "Media group",
            round(matched_posts_per_1000_published, 1) as "Per 1,000 own posts"
        from event_group_coverage
        where event_slug = {{event_slug}}
        order by matched_posts_per_1000_published desc
        """,
        "bar",
        {"graph.dimensions": ["Media group"], "graph.metrics": ["Per 1,000 own posts"]},
        True,
    ),
    card(
        "Who published first",
        "Hours between the search window opening and each group's first matched post. The "
        "window opens at the same moment for every group, so these are comparable.",
        """
        select
            media_group        as "Media group",
            coverage_lag_hours as "Hours to first post"
        from event_group_coverage
        where event_slug = {{event_slug}}
          and coverage_lag_hours is not null
        order by coverage_lag_hours
        """,
        "bar",
        {"graph.dimensions": ["Media group"], "graph.metrics": ["Hours to first post"]},
        True,
    ),
    card(
        "Coverage day by day",
        "Matched posts per group per day of the event window. Days with no coverage are real "
        "zeros, not gaps in the data.",
        """
        select
            coverage_date  as "Day",
            media_group    as "Media group",
            matched_posts  as "Matched posts"
        from event_group_daily
        where event_slug = {{event_slug}}
        order by coverage_date, media_group
        """,
        "line",
        {"graph.dimensions": ["Day", "Media group"], "graph.metrics": ["Matched posts"]},
        True,
    ),
    card(
        "Words and phrases that separate the groups",
        "Not the most common words — those are the same for everyone. These are the words one "
        "group used that the other groups covering the same event did not. Word counting only: "
        "it makes no claim about tone or intent.",
        """
        select
            media_group             as "Media group",
            term_type               as "Kind",
            term_label              as "Word or phrase",
            posts_with_term         as "Posts using it",
            group_posts             as "Posts by the group",
            round(100 * share_in_group, 1)   as "% of this group",
            round(100 * share_elsewhere, 1)  as "% of everyone else",
            sources_with_term       as "Channels using it"
        from event_group_terms
        where event_slug = {{event_slug}}
          and distinctiveness_rank <= 8
        order by media_group, term_type, distinctiveness_rank
        """,
        "table", {}, True,
    ),
    card(
        "The posts behind the numbers",
        "The matched posts themselves, most relevant first, with the relevance score that let "
        "each one into the set.",
        """
        select
            published_at         as "Published (UTC)",
            source_name          as "Source",
            media_group          as "Media group",
            round(rerank_score, 3) as "Relevance",
            views                as "Views",
            forwards             as "Forwards",
            post_text            as "Post"
        from event_message_detail
        where event_slug = {{event_slug}}
        order by rerank_score desc
        limit 200
        """,
        "table", {}, True,
    ),
]


def ensure_cards(client: Metabase, database_id: int) -> list[dict]:
    """Create or update every saved question, matched by name."""
    existing = {c["name"]: c for c in client.call("GET", "card") or []}
    result = []
    for spec in CARDS:
        native = {"query": spec["sql"].strip()}
        native["template-tags"] = dict(EVENT_TAG) if spec["filtered"] else {}
        payload = {
            "name": spec["name"],
            "description": spec["description"],
            "display": spec["display"],
            "visualization_settings": spec["settings"],
            "dataset_query": {
                "type": "native",
                "native": native,
                "database": database_id,
            },
        }
        if spec["name"] in existing:
            card_id = existing[spec["name"]]["id"]
            client.call("PUT", f"card/{card_id}", payload)
            print(f"  updated: {spec['name']}")
        else:
            card_id = client.call("POST", "card", payload)["id"]
            print(f"  created: {spec['name']}")
        result.append({**spec, "id": card_id})
    return result


EVENT_PARAMETER = {
    "name": "Event",
    "slug": "event",
    "id": "9d1e77aa",
    "type": "string/=",
    "sectionId": "string",
    "default": [DEFAULT_EVENT_SLUG],
}


def ensure_dashboard(client: Metabase, cards: list[dict]) -> int:
    """Create or refresh the dashboard and lay the cards out on it."""
    existing = next(
        (d for d in client.call("GET", "dashboard") or [] if d["name"] == DASHBOARD_NAME),
        None,
    )
    if existing:
        dashboard_id = existing["id"]
        print(f"  dashboard already present (id {dashboard_id})")
    else:
        dashboard_id = client.call(
            "POST",
            "dashboard",
            {
                "name": DASHBOARD_NAME,
                "description": (
                    "How Russian media groups covered the events people noticed. Every number "
                    "is computed in SQL from the matched post sets in the warehouse."
                ),
            },
        )["id"]
        print(f"  created dashboard (id {dashboard_id})")

    # Full-width for the wide tables, half-width for the paired charts.
    layout = [
        (0, GRID_WIDTH, 7),     # event list
        (0, GRID_WIDTH // 2, 7),  # scatter
        (GRID_WIDTH // 2, GRID_WIDTH // 2, 7),  # cross-event table
        (0, GRID_WIDTH // 2, 7),  # coverage by group
        (GRID_WIDTH // 2, GRID_WIDTH // 2, 7),  # per 1,000
        (0, GRID_WIDTH // 2, 6),  # who published first
        (GRID_WIDTH // 2, GRID_WIDTH // 2, 6),  # day by day
        (0, GRID_WIDTH, 9),     # terms
        (0, GRID_WIDTH, 10),    # posts
    ]

    dashcards = []
    row = 0
    previous_col_end = GRID_WIDTH
    # strict=True: one layout entry per card, so a card added without a layout entry is an
    # error here rather than a card silently missing from the dashboard.
    for index, (spec, (col, size_x, size_y)) in enumerate(zip(cards, layout, strict=True)):
        dashcards.append(
            {
                "id": -(index + 1),
                "card_id": spec["id"],
                "row": row,
                "col": col,
                "size_x": size_x,
                "size_y": size_y,
                "parameter_mappings": (
                    [
                        {
                            "parameter_id": EVENT_PARAMETER["id"],
                            "card_id": spec["id"],
                            "target": ["variable", ["template-tag", "event_slug"]],
                        }
                    ]
                    if spec["filtered"]
                    else []
                ),
                "visualization_settings": {},
            }
        )
        # Move to the next row once the current one is filled.
        previous_col_end = col + size_x
        if previous_col_end >= GRID_WIDTH:
            row += size_y

    client.call(
        "PUT",
        f"dashboard/{dashboard_id}",
        {"dashcards": dashcards, "parameters": [EVENT_PARAMETER]},
    )
    print(f"  placed {len(dashcards)} cards")
    return dashboard_id


def main() -> None:
    username = os.environ.get("METABASE_USER")
    password = os.environ.get("METABASE_PASSWORD")
    if not username or not password:
        print(
            "Set METABASE_USER and METABASE_PASSWORD to the admin account you created at\n"
            f"{METABASE_URL} on first run. This script never creates that account, so the\n"
            "password stays yours.\n\n"
            "  METABASE_USER='you@example.com' METABASE_PASSWORD='...' \\\n"
            "      .venv/bin/python metabase/provision.py",
            file=sys.stderr,
        )
        raise SystemExit(2)

    client = Metabase(METABASE_URL)
    print(f"Waiting for Metabase at {METABASE_URL} ...")
    wait_until_up(client)

    if client.needs_first_run_setup():
        raise SystemExit(
            f"Metabase is running but has no admin account yet.\n"
            f"Open {METABASE_URL} and create one — pick your own email and password, they are\n"
            "never set or stored by anything in this repository. Then run this script again."
        )

    client.log_in(username, password)
    print("Signed in.")

    print("Database connection:")
    database_id = ensure_database(client)
    wait_for_tables(client, database_id, expected=7)

    print("Questions:")
    cards = ensure_cards(client, database_id)

    print("Dashboard:")
    dashboard_id = ensure_dashboard(client, cards)

    print(f"\nDone. Open {METABASE_URL}/dashboard/{dashboard_id}")


if __name__ == "__main__":
    main()
