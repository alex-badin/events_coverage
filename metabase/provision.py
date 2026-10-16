#!/usr/bin/env python3
"""Build the Events coverage dashboards inside a running Metabase.

Metabase is normally set up by clicking, which means the setup exists only on the machine
where the clicking happened. This script does the same work through Metabase's own
interface, so the dashboards can be rebuilt from scratch on any machine and live in git as
code rather than as screenshots.

It builds two dashboards that mirror the standalone page in dashboard/:

  Events coverage — Overview   every survey week at once: what people noticed, how each
                               theme was put together, and the coverage measured so far
  Events coverage — Week       one survey week: what people named, then one event's
                               coverage by media group and the posts behind it

Clicking a week or an event on the Overview opens the Week dashboard with its filters set;
clicking a theme on the Week dashboard goes back to the Overview filtered on that theme.

It is safe to run repeatedly: the collection, the database connection, every question and
both dashboards are matched by name and updated in place rather than duplicated. The
single-page dashboard this replaced, and its questions, are archived (Metabase's trash),
not deleted.

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
import uuid
from dataclasses import dataclass
from pathlib import Path

METABASE_URL = os.environ.get("METABASE_URL", "http://localhost:3000").rstrip("/")
DB_PATH_IN_CONTAINER = os.environ.get("DUCKDB_IN_CONTAINER", "/data/events.duckdb")
DB_NAME = "Events coverage warehouse"
COLLECTION_NAME = "Events coverage"
OVERVIEW_NAME = "Events coverage — Overview"
WEEK_NAME = "Events coverage — Week"

# What the single-page version of this script built. Archived on every run so an old setup
# does not sit next to the new one; a name the new setup reuses is updated instead.
RETIRED_DASHBOARDS = ["Events coverage"]
RETIRED_CARDS = [
    "Events: public attention against coverage",
    "Survey share against matched posts",
    "Which events landed with which kinds of media",
    "Coverage by media group",
    "Share of a group's own output",
    "Who published first",
    "Coverage day by day",
    "Words and phrases that separate the groups",
    "The posts behind the numbers",
]

# The published copy on this machine — the same file the container reads at
# DB_PATH_IN_CONTAINER. Read for the lists the filters offer and the week the Week
# dashboard opens on, so neither goes stale when the data changes.
PUBLISHED_DB = Path(__file__).resolve().parent / "data" / "events.duckdb"

# The marts the questions read. scripts/publish_warehouse_for_metabase.py publishes them.
MARTS_USED = [
    "survey_weeks",
    "week_events",
    "theme_week_attention",
    "theme_group_coverage",
    "event_overview",
    "event_group_coverage",
    "event_group_daily",
    "event_group_terms",
    "event_message_detail",
]

# The order media groups appear in — the same as scripts/export_dashboard_data.py uses for
# the standalone page, so the two read alike.
GROUP_ORDER = [
    "State agencies",
    "Federal TV and state broadcasters",
    "Pro-government online media",
    "Mainstream business and general media",
    "Independent and exile media",
    "War and military channels",
]

# The news corpus ends here (AGENTS.md). The publish step drops the activity table this
# date is read from, so it is stated rather than queried.
NEWS_DATA_ENDS = "2 April 2025"

# Metabase lays dashboards out on a grid 24 columns wide.
GRID_WIDTH = 24


# ---------------------------------------------------------------------------------------
# What the published warehouse holds
# ---------------------------------------------------------------------------------------

@dataclass
class Snapshot:
    areas: list[str]                    # area labels, in the seed's order
    themes: list[str]                   # theme labels, grouped by area
    weeks: list[list[str]]              # [week key, dropdown label], newest first
    default_week: str                   # the latest week with measured coverage


def week_dates(start, end) -> str:
    """'3–9 Mar 2025', the way the standalone page writes a week."""
    if start.year != end.year:
        return f"{start.day} {start:%b %Y} – {end.day} {end:%b %Y}"
    if start.month != end.month:
        return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"
    return f"{start.day}–{end.day} {end:%b %Y}"


def read_snapshot() -> Snapshot:
    import duckdb

    if not PUBLISHED_DB.exists():
        raise SystemExit(
            f"{PUBLISHED_DB} is missing. Run:\n"
            "  .venv/bin/python scripts/publish_warehouse_for_metabase.py"
        )
    with duckdb.connect(str(PUBLISHED_DB), read_only=True) as con:
        present = {row[0] for row in con.execute(
            "select table_name from information_schema.tables where table_schema = 'main'"
        ).fetchall()}
        missing = [name for name in MARTS_USED if name not in present]
        if missing:
            raise SystemExit(
                f"{PUBLISHED_DB} lacks {', '.join(missing)}. Run dbt build, then:\n"
                "  .venv/bin/python scripts/publish_warehouse_for_metabase.py"
            )

        themes = con.execute(
            """
            select distinct umbrella_label, umbrella_order, theme_label, theme_order
            from theme_week_attention
            order by umbrella_order, theme_order
            """
        ).fetchall()
        weeks = con.execute(
            """
            select fom_year, fom_week, week_start, week_end, n_measured_events
            from survey_weeks
            where has_survey
            order by week_start desc
            """
        ).fetchall()
        groups = {row[0] for row in con.execute(
            "select distinct media_group from theme_group_coverage"
        ).fetchall()}

    # A group the data has but this list does not would silently vanish from the coverage
    # table, so stop instead.
    unknown = groups - set(GROUP_ORDER)
    if unknown:
        raise SystemExit(
            f"Media groups not in GROUP_ORDER: {', '.join(sorted(unknown))}. "
            "Add them to GROUP_ORDER in metabase/provision.py."
        )

    week_options = []
    measured = []
    for year, week, start, end, n_measured in weeks:
        key = f"{year}-W{week:02d}"
        label = f"{key} · {week_dates(start, end)}"
        if n_measured:
            label += " · coverage measured"
            measured.append(key)
        week_options.append([key, label])

    return Snapshot(
        areas=list(dict.fromkeys(row[0] for row in themes)),
        themes=[row[2] for row in themes],
        weeks=week_options,
        default_week=measured[0] if measured else week_options[0][0],
    )


# ---------------------------------------------------------------------------------------
# Talking to Metabase
# ---------------------------------------------------------------------------------------

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


def ensure_collection(client: Metabase) -> int:
    """One folder for both dashboards and every question they use."""
    for collection in client.call("GET", "collection") or []:
        if collection.get("name") == COLLECTION_NAME and not collection.get("archived"):
            print(f"  collection already present (id {collection['id']})")
            return collection["id"]
    created = client.call("POST", "collection", {"name": COLLECTION_NAME, "parent_id": None})
    print(f"  created collection (id {created['id']})")
    return created["id"]


def ensure_database(client: Metabase) -> int:
    """Create the DuckDB connection, or re-read the schema of the existing one."""
    listed = client.call("GET", "database")
    databases = listed["data"] if isinstance(listed, dict) else listed
    for database in databases:
        if database["name"] == DB_NAME:
            # The published file may have gained marts since Metabase last read it.
            client.call("POST", f"database/{database['id']}/sync_schema")
            print(f"  connection already present (id {database['id']}), schema re-read")
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


def wait_for_tables(client: Metabase, database_id: int, seconds: int = 180) -> None:
    """Metabase reads the schema in the background; wait until every mart used is visible."""
    deadline = time.time() + seconds
    missing = set(MARTS_USED)
    while time.time() < deadline:
        tables = client.call("GET", f"database/{database_id}/metadata").get("tables", [])
        missing = set(MARTS_USED) - {table["name"] for table in tables}
        if not missing:
            print(f"  all {len(MARTS_USED)} marts visible")
            return
        time.sleep(3)
    raise RuntimeError(
        f"Not visible after {seconds}s: {', '.join(sorted(missing))}. "
        "If this is a driver problem the reason is in: docker logs events-coverage-metabase"
    )


# ---------------------------------------------------------------------------------------
# SQL building blocks
#
# The questions below are written as they appear in Metabase. {{week}} and the like are
# Metabase filter variables; text inside [[ ]] is dropped when its variable is empty.
# <<name>> marks a shared piece that fill() splices in before the SQL is sent.
# ---------------------------------------------------------------------------------------

def quote(text: str) -> str:
    """A SQL string literal."""
    return "'" + text.replace("'", "''") + "'"


def ident(text: str) -> str:
    """A SQL column name."""
    return '"' + text.replace('"', '""') + '"'


def fill(sql: str, **pieces: str) -> str:
    for name, piece in pieces.items():
        sql = sql.replace(f"<<{name}>>", piece)
    if "<<" in sql:
        raise ValueError(f"unfilled piece in: {sql[sql.index('<<'):][:40]}")
    return sql.strip()


def dates_sql(start: str, end: str) -> str:
    """'3–9 Mar 2025' in SQL, matching week_dates() above."""
    return (
        f"case when year({start}) <> year({end}) "
        f"then strftime({start}, '%-d %b %Y') || ' – ' || strftime({end}, '%-d %b %Y') "
        f"when month({start}) <> month({end}) "
        f"then strftime({start}, '%-d %b') || ' – ' || strftime({end}, '%-d %b %Y') "
        f"else strftime({start}, '%-d') || '–' || strftime({end}, '%-d %b %Y') end"
    )


def coverage_cell(posts: str, per_1000: str, published: str) -> str:
    """One media group's coverage as text, keeping the three kinds of zero apart.

    'not publishing in this window' — the group published nothing at all then;
    '0 of N posts' — it published N posts and none matched;
    'too few to compare' — under 5 matched posts.
    """
    return (
        f"case when coalesce({published}, 0) = 0 then 'not publishing in this window' "
        f"when {posts} = 0 then '0 of ' || format('{{:,}}', {published}) || ' posts' "
        f"else printf('%.1f', {per_1000}) || ' · ' || format('{{:,}}', {posts}) "
        f"|| case when {posts} = 1 then ' post' else ' posts' end "
        f"|| case when {posts} < 5 then ', too few to compare' else '' end end"
    )


def group_columns(cell: str) -> str:
    """One column per media group, in GROUP_ORDER, from rows carrying media_group and a cell.
    A group with no row published nothing in the window."""
    return ",\n        ".join(
        f"coalesce(max({cell}) filter (where media_group = {quote(g)}), "
        f"'not publishing in this window') as {ident(g)}"
        for g in GROUP_ORDER
    )


def group_order_sql(column_sql: str) -> str:
    return f"list_position([{', '.join(quote(g) for g in GROUP_ORDER)}], {column_sql})"


# The event the Week dashboard shows: the one picked in the Event filter if it is on this
# week's list, else the week's first event with measured coverage, else its top event —
# the same rule as the standalone page. A pick left over from another week falls back
# rather than showing an event from the wrong week.
CHOSEN_EVENT = """
chosen as (
    select *
    from week_events
    where printf('%d-W%02d', fom_year, fom_week) = {{week}}
      and event_kind = 'specific event'
    order by
        [[(event_name = {{event}}) desc,]]
        (coverage_status = 'measured') desc,
        rank_in_week
    limit 1
)"""

# Which events the Area and Theme filters keep. The narrowest one picked decides — a
# theme, else an area, else every event — so a theme picked from another area than the
# Area filter shows its events rather than nothing. The totals row of "Coverage measured
# so far" is read for the same scope.
SCOPE_FILTER = """coalesce(
        [[coalesce(theme_label, '') = {{theme}},]]
        [[coalesce(umbrella_label, '') = {{area}},]]
        true
    )"""

# Why an event's counts may not compare with other events'. Two separate reasons that pull
# in opposite directions, so they are never merged into one vague flag.
WARNING = """nullif(concat_ws(' ',
        case when not o.standard_relevance_cutoff
             then 'Posts were kept at a relevance score of ' || o.rerank_threshold
                  || ' instead of 0.35, so weaker matches were counted and the total is '
                  || 'too high next to other events.'
        end,
        case when o.searchable_share_of_window < 0.9
             then 'Only ' || format('{:,}', o.searchable_posts_in_window) || ' of '
                  || format('{:,}', o.posts_published_in_window)
                  || ' posts in the window could be searched, so the total is too low '
                  || 'next to other events.'
        end
    ), '')"""


@dataclass
class Card:
    key: str                  # how the layout refers to it
    name: str                 # the question's name in Metabase, which is how it is matched
    description: str
    sql: str
    display: str = "table"
    settings: dict | None = None
    tags: tuple[str, ...] = ()  # the filter variables the SQL uses
    id: int | None = None


def column(name: str) -> str:
    """The key Metabase files one column's settings under."""
    return json.dumps(["name", name])


# ---------------------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------------------

def overview_cards(snap: Snapshot) -> list[Card]:
    area_columns = ",\n    ".join(
        f"sum(mentions) filter (where umbrella_label = {quote(a)}) as {ident(a)}"
        for a in snap.areas
    )
    return [
        Card(
            "weeks", "Survey weeks",
            "Calendar weeks for which FOM published a weekly list of the events people named.",
            'select count(*) as "Survey weeks" from survey_weeks where has_survey',
            display="scalar",
        ),
        Card(
            "events", "Named events",
            "Specific events on those lists. FOM's catch-all categories and the share who "
            "could not name anything are not counted.",
            "select count(*) as \"Named events\" from week_events "
            "where event_kind = 'specific event'",
            display="scalar",
        ),
        Card(
            "measured", "Events with measured coverage",
            "Events with a matched post set. Sets are built one event at a time and cost "
            "money, so this is a curated handful, not a sample; every other event is "
            "'not measured yet', never zero.",
            "select count(*) as \"Events with measured coverage\" from week_events "
            "where coverage_status = 'measured'",
            display="scalar",
        ),
        Card(
            "posts", "Distinct matched posts",
            "Posts matched to any measured event, each counted once: search windows of "
            "neighbouring weeks overlap, so one post can match two events.",
            'select sum(distinct_matched_posts) as "Distinct matched posts" '
            "from theme_group_coverage where scope_type = 'all'",
            display="scalar",
        ),
        Card(
            "heatmap", "What people noticed, week by week",
            "One row per calendar week, one column per area of news. Each cell adds up the "
            "shares of the area's events that week: mentions per 100 respondents, not a "
            "share of people, because one person can name two events. A blank cell is a "
            "week in which nothing in that area was named; weeks without a FOM list say so. "
            "Click a week to open it.",
            fill("""
with area_weeks as (
    select week_start, umbrella_label, sum(attention_sum) as mentions
    from theme_week_attention
    group by all
)
select
    printf('%d-W%02d', w.fom_year, w.fom_week)  as "Week",
    <<dates>> || case when w.has_survey then '' else ' · no FOM survey' end  as "Dates",
    <<areas>>,
    nullif(w.n_measured_events, 0)  as "Events with measured coverage"
from survey_weeks as w
left join area_weeks using (week_start)
group by w.week_start, w.week_end, w.fom_year, w.fom_week, w.has_survey, w.n_measured_events
order by w.week_start desc
""", dates=dates_sql("w.week_start", "w.week_end"), areas=area_columns),
            settings={
                "column_settings": {column(a): {"decimals": 0} for a in snap.areas},
                # Shade the area columns like a heatmap, in the standalone page's five bands.
                # Metabase applies the first rule a cell matches, so the darkest comes first.
                # Bands rather than a colour range, because a range leaves every value above
                # its top unshaded. Blank cells stay unshaded.
                "table.column_formatting": [
                    {
                        "id": index,
                        "columns": snap.areas,
                        "type": "single",
                        "operator": ">=",
                        "value": floor,
                        "color": colour,
                        "highlight_row": False,
                    }
                    for index, (floor, colour) in enumerate([
                        (30, "#5B92D6"),
                        (15, "#8DB4E6"),
                        (6, "#B9D1F0"),
                        (3, "#DAE7F7"),
                        (0, "#EEF4FB"),
                    ])
                ],
            },
        ),
        Card(
            "scope_weeks", "Week by week for the area or theme picked",
            "Every survey week in which the area or theme picked in the filters was named "
            "(every event, when nothing is picked). Mentions per 100 respondents adds up "
            "the shares of its events that week. Click a week to open it.",
            fill("""
with scoped as (
    select
        *,
        max(attention_percentage) over (partition by week_start)  as top_share
    from week_events
    where event_kind = 'specific event'
      and <<scope>>
)
select
    printf('%d-W%02d', fom_year, fom_week)  as "Week",
    sum(attention_percentage)               as "Mentions per 100 respondents",
    count(*)                                as "Events named",
    case
        when count(*) filter (where attention_percentage = top_share) > 1
        then 'joint top (' || count(*) filter (where attention_percentage = top_share)
             || ' events), e.g. ' || min(event_name) filter (where attention_percentage = top_share)
        else min(event_name) filter (where attention_percentage = top_share)
    end                                     as "Top event",
    max(top_share)                          as "Top event share %",
    nullif(count(*) filter (where coverage_status = 'measured'), 0)
                                            as "Events with measured coverage"
from scoped
group by week_start, fom_year, fom_week
order by week_start desc
""", scope=SCOPE_FILTER),
            settings={"column_settings": {column("Mentions per 100 respondents"): {"decimals": 0}}},
            tags=("area", "theme"),
        ),
        Card(
            "wordings", "How this theme was put together",
            "Every FOM wording grouped into the area or theme picked, with the weeks it was "
            "named. This is where to check that a theme really holds one subject across the "
            "years. Click the first or last week to open it on that event.",
            fill("""
select
    event_name                                           as "FOM wording",
    count(*)                                             as "Weeks named",
    arg_min(printf('%d-W%02d', fom_year, fom_week), week_start)  as "First named",
    arg_max(printf('%d-W%02d', fom_year, fom_week), week_start)  as "Last named",
    max(attention_percentage)                            as "Peak share %",
    nullif(count(*) filter (where coverage_status = 'measured'), 0)  as "Measured",
    theme_label                                          as "Theme",
    umbrella_label                                       as "Area"
from week_events
where event_kind = 'specific event'
  and <<scope>>
group by all
order by "Weeks named" desc, "First named"
""", scope=SCOPE_FILTER),
            tags=("area", "theme"),
        ),
        Card(
            "coverage", "Coverage measured so far",
            "One row per measured event in the area or theme picked, one column per media "
            "group: matched posts per 1,000 posts the group published in the event's window, "
            "on any topic. '0 of N posts' means the group published and matched nothing; "
            "'not publishing in this window' means it published nothing at all. The last "
            "row adds the events up with each post counted once, divided by what the group "
            "published over the days the windows cover, each day once. ⚠ marks an event "
            "whose counts cannot be compared with the others. Click an event to open it.",
            fill("""
with scope as (
    -- The totals row is read for the narrowest scope picked: a theme, else an area, else
    -- everything.
    select coalesce(
        [[(select any_value('theme|' || theme_id) from week_events
           where theme_label = {{theme}}),]]
        [[(select any_value('umbrella|' || umbrella_id) from week_events
           where umbrella_label = {{area}}),]]
        'all|all'
    ) as scope_key
),

measured as (
    select week_events.*, o.standard_relevance_cutoff, o.searchable_share_of_window
    from week_events
    inner join event_overview as o using (event_id)
    where coverage_status = 'measured'
      and <<scope>>
),

event_rows as (
    select
        1                                           as sort_group,
        m.week_start                                as sort_week,
        printf('%d-W%02d', m.fom_year, m.fom_week)  as "Week",
        case when not m.standard_relevance_cutoff or m.searchable_share_of_window < 0.9
             then '⚠ ' else '' end || coalesce(m.event_label_en, m.event_name)  as "Event",
        m.event_name                                as "FOM wording",
        m.attention_percentage                      as "Named by %",
        <<event_groups>>
    from measured as m
    left join (
        select event_id, media_group,
               <<event_cell>> as cell
        from event_group_coverage
    ) as g using (event_id)
    group by all
),

-- The two rows below leave "Event" empty, so they carry no link to the Week dashboard.
total_row as (
    select
        2,
        null,
        null,
        null,
        'All ' || max(n_measured_events) || ' measured events together: posts about any of '
            || 'them per 1,000 posts the group published over the ' || max(union_window_days)
            || ' days their windows cover; a post about two events counts once',
        null,
        <<total_groups>>
    from (
        select *, <<total_cell>> as cell
        from theme_group_coverage
        where scope_type || '|' || scope_id = (select scope_key from scope)
    )
    having max(n_measured_events) > 1
),

nothing_row as (
    select 3, null, null, null,
           'No event here has measured coverage yet. The weeks it was named are listed above.',
           null,
           <<nothing_groups>>
    where not exists (select 1 from measured)
)

select "Week", "Event", "FOM wording", "Named by %", <<group_names>>
from (
    select * from event_rows
    union all select * from total_row
    union all select * from nothing_row
)
order by sort_group, sort_week desc
""",
                scope=SCOPE_FILTER,
                event_groups=group_columns("g.cell"),
                event_cell=coverage_cell(
                    "matched_posts", "matched_posts_per_1000_published",
                    "posts_published_in_window",
                ),
                total_groups=group_columns("cell"),
                total_cell=coverage_cell(
                    "distinct_matched_posts", "matched_posts_per_1000_published",
                    "posts_published_in_union_window",
                ),
                nothing_groups=", ".join("null" for _ in GROUP_ORDER),
                group_names=", ".join(ident(g) for g in GROUP_ORDER),
            ),
            tags=("area", "theme"),
        ),
    ]


# ---------------------------------------------------------------------------------------
# Week
# ---------------------------------------------------------------------------------------

def week_cards() -> list[Card]:
    return [
        Card(
            "header", "The survey week",
            "The week picked in the Week filter. Click the previous or next survey week, or "
            "the nearest week with measured coverage, to move there. FOM did not publish a "
            "list every week, so the steps skip weeks without one.",
            fill("""
with weeks as (
    select *, printf('%d-W%02d', fom_year, fom_week) as week_key
    from survey_weeks
),
this_week as (
    select * from weeks where week_key = {{week}}
)
select
    t.week_key                                   as "Week",
    <<dates>>                                     as "Dates",
    case when t.has_survey then t.n_specific_events || ' events named'
         else 'no FOM survey this week' end      as "Survey",
    t.non_response_percentage                    as "Could not name an event %",
    nullif(t.n_measured_events, 0)               as "Events with measured coverage",
    (select max(week_key) from weeks where has_survey and week_start < t.week_start)
                                                 as "‹ Previous survey week",
    (select min(week_key) from weeks where has_survey and week_start > t.week_start)
                                                 as "Next survey week ›",
    coalesce((select max(week_key) from weeks
              where n_measured_events > 0 and week_start < t.week_start), 'none earlier')
                                                 as "‹ Measured coverage",
    coalesce((select min(week_key) from weeks
              where n_measured_events > 0 and week_start > t.week_start), 'none later')
                                                 as "Measured coverage ›"
from this_week as t
""", dates=dates_sql("t.week_start", "t.week_end")),
            tags=("week",),
        ),
        Card(
            "list", "What people named this week",
            "Every row of the week's FOM list, by share of respondents. People could name "
            "several events, so the shares need not add up to 100. Click an event to show its "
            "coverage below; click a theme to see it across all weeks.",
            fill("""
with <<chosen>>
select
    case when w.event_id = (select event_id from chosen) then '▶' else '' end
                                                as "Shown",
    w.rank_in_week                              as "#",
    w.attention_percentage                      as "Share %",
    w.event_name                                as "FOM wording",
    w.event_label_en                            as "English label",
    w.theme_label                               as "Theme",
    case
        when w.event_kind = 'catch-all category'  then 'FOM catch-all category'
        when w.event_kind = 'survey non-response' then 'could not name an event'
        when w.coverage_status = 'measured'       then 'coverage measured'
        when w.coverage_status = 'no post passed the cut-off'
                                                  then 'searched, nothing passed the cut-off'
        else 'not measured yet'
    end                                         as "Coverage",
    w.matched_posts                             as "Matched posts"
from week_events as w
where printf('%d-W%02d', w.fom_year, w.fom_week) = {{week}}
order by
    w.event_kind = 'specific event' desc,
    w.event_kind = 'catch-all category' desc,
    w.rank_in_week,
    w.attention_percentage desc
""", chosen=CHOSEN_EVENT),
            tags=("week", "event"),
        ),
        Card(
            "event", "The event shown",
            "The event picked on the list, or the week's first event with measured coverage. "
            "An event without a matched post set reads 'not measured yet', never zero.",
            fill("""
with <<chosen>>,
counts as (
    select
        count(*) filter (where event_kind = 'specific event')  as n_events,
        count(*) filter (where coverage_status = 'measured')   as n_measured
    from week_events
)
select
    coalesce(c.event_label_en, c.event_name)    as "Event",
    c.event_name                                as "FOM wording",
    printf('%d-W%02d', c.fom_year, c.fom_week)  as "Week",
    c.attention_percentage                      as "Named by % of respondents",
    c.theme_label                               as "Theme",
    c.umbrella_label                            as "Area",
    case c.coverage_status
        when 'measured' then 'measured'
        when 'no post passed the cut-off' then
            'searched, but no post passed the 0.35 relevance cut-off: a result of the '
            || 'search, not a sign that the media were silent'
        else 'not measured yet: matched post sets are built one event at a time and cost '
             || 'money, so ' || counts.n_measured || ' of '
             || format('{:,}', counts.n_events) || ' events have one so far'
    end                                         as "Coverage",
    case when o.event_id is not null then
        strftime(o.match_start, '%-d %b') || ' – '
        || strftime(o.match_end_exclusive - 1, '%-d %b %Y')
    end                                         as "Posts searched",
    o.matched_posts                             as "Matched posts",
    case when o.event_id is not null then
        o.sources_covering || ' of ' || o.sources_active || ' publishing sources · '
        || o.groups_covering || ' of ' || o.groups_active || ' media groups'
    end                                         as "Who covered it",
    <<warning>>                                 as "⚠ Cannot be compared with other events",
    array_to_string(regexp_extract_all(c.quote_examples, '«[^»]*»'), '  ')
                                                as "What respondents said",
    case when o.event_id is not null then
        case when o.retriever = 'qwen3' then 'Qwen3 embeddings over the whole corpus'
             else 'older Cohere embeddings, part of the corpus' end
        || '; kept when ' || o.rerank_model || ' scored it ' || o.rerank_threshold
        || ' or more; ' || format('{:,}', o.candidates_reranked) || ' candidates scored; '
        || cast(round(100 * o.searchable_share_of_window) as integer)
        || '% of the window searchable; relevance kept median '
        || printf('%.2f', o.median_relevance_score)
        || ', lowest ' || printf('%.2f', o.min_relevance_score)
        || '; built ' || strftime(o.built_at, '%Y-%m-%d')
    end                                         as "How the posts were matched"
from chosen as c
cross join counts
left join event_overview as o using (event_id)
""", chosen=CHOSEN_EVENT, warning=WARNING),
            display="object",
            tags=("week", "event"),
        ),
        Card(
            "bars", "How each media group covered it",
            "Matched posts per 1,000 posts the group published in the event's window, on any "
            "topic — what stops the largest publishers from automatically looking the most "
            "interested. Empty when the event's coverage is not measured. Click a group to "
            "narrow the words and posts to it.",
            fill("""
with <<chosen>>
select
    g.media_group                                 as "Media group",
    round(g.matched_posts_per_1000_published, 1)  as "Per 1,000 own posts"
from event_group_coverage as g
inner join chosen using (event_id)
order by <<order>>
""", chosen=CHOSEN_EVENT, order=group_order_sql("g.media_group")),
            display="row",
            settings={
                "graph.dimensions": ["Media group"],
                "graph.metrics": ["Per 1,000 own posts"],
                "graph.show_values": True,
            },
            tags=("week", "event"),
        ),
        Card(
            "numbers", "Every number, by media group",
            "Every media group, including the ones with nothing to show: '0 of N posts' "
            "means the group published N posts in the window and none matched; 'not "
            "publishing in this window' means it published nothing at all then. Fewer than "
            "5 matched posts are too few to compare.",
            fill("""
with <<chosen>>,
groups as (
    select unnest([<<groups>>]) as media_group
)
select
    groups.media_group                            as "Media group",
    <<cell>>                                      as "Coverage",
    g.matched_posts                               as "Matched posts",
    round(g.matched_posts_per_1000_published, 1)  as "Per 1,000 own posts",
    round(100 * g.share_of_voice)                 as "Share of the event's posts %",
    case when g.sources_active > 0
         then g.sources_covering || ' of ' || g.sources_active end  as "Sources covering",
    g.coverage_lag_hours                          as "First post after (hours)",
    round(g.views_per_matched_post)               as "Views per post",
    round(g.mean_relevance_score, 2)              as "Mean relevance"
from groups
cross join chosen as c
left join event_group_coverage as g
    on g.event_id = c.event_id and g.media_group = groups.media_group
where c.coverage_status = 'measured'
order by <<order>>
""",
                chosen=CHOSEN_EVENT,
                groups=", ".join(quote(g) for g in GROUP_ORDER),
                cell=coverage_cell(
                    "g.matched_posts", "g.matched_posts_per_1000_published",
                    "g.posts_published_in_window",
                ),
                order=group_order_sql("groups.media_group"),
            ),
            tags=("week", "event"),
        ),
        Card(
            "daily", "Coverage day by day",
            "Matched posts per group per day of the event's search window, which runs from "
            "3 days before the survey week to 10 days after it. Days with no coverage are "
            "real zeros, not gaps in the data.",
            fill("""
with <<chosen>>
select
    d.coverage_date   as "Day",
    d.media_group     as "Media group",
    d.matched_posts   as "Matched posts"
from event_group_daily as d
inner join chosen using (event_id)
order by d.coverage_date, <<order>>
""", chosen=CHOSEN_EVENT, order=group_order_sql("d.media_group")),
            display="line",
            settings={
                "graph.dimensions": ["Day", "Media group"],
                "graph.metrics": ["Matched posts"],
            },
            tags=("week", "event"),
        ),
        Card(
            "words", "Words a group used more than the others",
            "Not the most common words — those are the same for everyone — but the words one "
            "group used on this event that the other groups covering it did not. Counting "
            "only: no claim about tone or intent. Pick a group to narrow the list; click a "
            "word to see exactly the posts it was counted in.",
            fill("""
with <<chosen>>
select
    t.media_group                                 as "Media group",
    t.term_label                                  as "Word or phrase",
    t.posts_with_term || ' of ' || t.group_posts  as "Posts using it",
    round(100 * t.share_in_group, 1)              as "% of this group",
    round(100 * t.share_elsewhere, 1)             as "% of everyone else",
    t.sources_with_term                           as "Channels using it"
from event_group_terms as t
inner join chosen using (event_id)
where t.distinctiveness_rank <= 8
  [[and t.media_group = {{group}}]]
order by <<order>>, t.distinctiveness_rank
""", chosen=CHOSEN_EVENT, order=group_order_sql("t.media_group")),
            tags=("week", "event", "group"),
        ),
        Card(
            "posts", "The posts behind the numbers",
            "The matched posts themselves, most relevant first, each with the relevance "
            "score that let it into the set. Narrow them with the Media group and Word "
            "filters.",
            fill("""
with <<chosen>>
select
    p.published_at                                 as "Published (UTC)",
    p.source_name                                  as "Source",
    p.media_group                                  as "Media group",
    round(p.rerank_score, 2)                       as "Relevance",
    p.views                                        as "Views",
    case when p.is_digest then 'roundup post' end  as "Kind",
    p.post_text                                    as "Post"
from event_message_detail as p
inner join chosen using (event_id)
where true
  [[and p.media_group = {{group}}]]
  [[and p.source_name || ':' || cast(p.message_id as varchar) in (
        -- The exact posts the word was counted in, carried out of the warehouse rather
        -- than matched again here, so the list is exactly what the number counts.
        select unnest(t.post_keys)
        from event_group_terms as t
        inner join chosen using (event_id)
        where t.term_label = {{word}}
  )]]
order by p.rerank_score desc
""", chosen=CHOSEN_EVENT),
            tags=("week", "event", "group", "word"),
        ),
    ]


# ---------------------------------------------------------------------------------------
# Filters, click-throughs and layout
# ---------------------------------------------------------------------------------------

def template_tag(name: str, display_name: str, default: str | None = None) -> dict:
    tag = {
        # Derived from the name, so a rerun produces the same id instead of a new one.
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"events-coverage/{name}")),
        "name": name,
        "display-name": display_name,
        "type": "text",
    }
    if default is not None:
        tag.update(default=default, required=True)
    return tag


def filter_parameter(slug: str, name: str, values=None, default=None) -> dict:
    """A dashboard filter. With values it is a dropdown; without, a free-text box that the
    click-throughs fill in."""
    parameter = {
        "id": slug,
        "slug": slug,
        "name": name,
        "type": "string/=",
        "sectionId": "string",
        "isMultiSelect": False,
    }
    if values is not None:
        parameter.update(
            values_query_type="list",
            values_source_type="static-list",
            values_source_config={"values": values},
        )
    else:
        parameter["values_query_type"] = "none"
    if default is not None:
        parameter.update(default=default, required=True)
    return parameter


def link(dashboard_id: int, **mapping: str) -> dict:
    """Click behaviour: open a dashboard with its filters set from the clicked row.

    mapping is filter id -> the column of the clicked row whose value it takes.
    """
    return {
        "type": "link",
        "linkType": "dashboard",
        "targetId": dashboard_id,
        "parameterMapping": {
            filter_id: {
                "id": filter_id,
                "source": {"type": "column", "id": source, "name": source},
                "target": {"type": "parameter", "id": filter_id},
            }
            for filter_id, source in mapping.items()
        },
    }


def crossfilter(**mapping: str) -> dict:
    """Click behaviour: set filters on the same dashboard from the clicked row.

    mapping is filter id -> the column of the clicked row whose value it takes.
    """
    return {
        "type": "crossfilter",
        "parameterMapping": {
            filter_id: {
                "id": filter_id,
                "source": {"type": "column", "id": source, "name": source},
                "target": {"type": "parameter", "id": filter_id},
            }
            for filter_id, source in mapping.items()
        },
    }


@dataclass
class Place:
    """Where one card sits on a dashboard, and what clicking it does.

    item is a Card, or markdown text for a text card. clicks maps a column name to its
    click behaviour; on_click is a click behaviour for the whole card (charts).
    """
    item: Card | str
    col: int
    row: int
    width: int
    height: int
    clicks: dict | None = None
    on_click: dict | None = None


def dashcard(index: int, place: Place, filter_ids: set[str]) -> dict:
    if place.col + place.width > GRID_WIDTH:
        raise ValueError(f"card {index} runs past the {GRID_WIDTH}-column grid")
    if isinstance(place.item, str):
        card_id, mappings = None, []
        settings = {
            "virtual_card": {
                "name": None, "display": "text", "visualization_settings": {},
                "dataset_query": {}, "archived": False,
            },
            "text": place.item,
        }
    else:
        card_id = place.item.id
        mappings = [
            {
                "parameter_id": tag,
                "card_id": card_id,
                "target": ["variable", ["template-tag", tag]],
            }
            for tag in place.item.tags
            if tag in filter_ids
        ]
        settings = {}
        if place.clicks:
            settings["column_settings"] = {
                column(name): {"click_behavior": behaviour}
                for name, behaviour in place.clicks.items()
            }
        if place.on_click:
            settings["click_behavior"] = place.on_click
    return {
        "id": -(index + 1),     # negative: a new dashcard
        "card_id": card_id,
        "row": place.row,
        "col": place.col,
        "size_x": place.width,
        "size_y": place.height,
        "parameter_mappings": mappings,
        "visualization_settings": settings,
    }


def ensure_cards(client: Metabase, database_id: int, collection_id: int,
                 cards: list[Card], tags: dict[str, dict]) -> None:
    """Create or update every saved question, matched by name."""
    existing = {c["name"]: c for c in client.call("GET", "card") or [] if not c.get("archived")}
    for card in cards:
        payload = {
            "name": card.name,
            "description": card.description,
            "display": card.display,
            "visualization_settings": card.settings or {},
            "collection_id": collection_id,
            "dataset_query": {
                "type": "native",
                "native": {
                    "query": card.sql.strip(),
                    "template-tags": {name: tags[name] for name in card.tags},
                },
                "database": database_id,
            },
        }
        if card.name in existing:
            card.id = existing[card.name]["id"]
            client.call("PUT", f"card/{card.id}", payload)
            print(f"  updated: {card.name}")
        else:
            card.id = client.call("POST", "card", payload)["id"]
            print(f"  created: {card.name}")


def ensure_dashboard(client: Metabase, name: str, description: str, collection_id: int) -> int:
    """Create the dashboard if missing; its cards and filters are set by place_cards()."""
    for dashboard in client.call("GET", "dashboard") or []:
        if dashboard["name"] == name and not dashboard.get("archived"):
            print(f"  {name}: already present (id {dashboard['id']})")
            return dashboard["id"]
    created = client.call(
        "POST", "dashboard",
        {"name": name, "description": description, "collection_id": collection_id},
    )
    print(f"  {name}: created (id {created['id']})")
    return created["id"]


def place_cards(client: Metabase, dashboard_id: int, parameters: list[dict],
                layout: list[Place]) -> None:
    """Replace the dashboard's cards and filters with the layout given.

    Sending the whole list each time means a rerun leaves exactly this layout, with no
    leftovers from an earlier version.
    """
    filter_ids = {p["id"] for p in parameters}
    dashcards = [dashcard(i, place, filter_ids) for i, place in enumerate(layout)]
    client.call(
        "PUT",
        f"dashboard/{dashboard_id}",
        {"dashcards": dashcards, "parameters": parameters, "width": "full"},
    )
    print(f"  placed {len(dashcards)} cards")


def retire_old_setup(client: Metabase, keep: set[str]) -> None:
    """Archive what the single-page version of this script built. Archived items sit in
    Metabase's trash and can be restored from there."""
    for dashboard in client.call("GET", "dashboard") or []:
        if dashboard["name"] in RETIRED_DASHBOARDS and not dashboard.get("archived"):
            client.call("PUT", f"dashboard/{dashboard['id']}", {"archived": True})
            print(f"  archived dashboard: {dashboard['name']}")
    for card in client.call("GET", "card") or []:
        if card["name"] in RETIRED_CARDS and card["name"] not in keep and not card.get("archived"):
            client.call("PUT", f"card/{card['id']}", {"archived": True})
            print(f"  archived question: {card['name']}")


def build_dashboards(client: Metabase, snap: Snapshot, overview: dict[str, Card],
                     week: dict[str, Card], collection_id: int) -> tuple[int, int]:
    overview_id = ensure_dashboard(
        client, OVERVIEW_NAME,
        "Every FOM survey week, 2020–2025: what people noticed, how each theme was put "
        "together, and the coverage measured so far.",
        collection_id,
    )
    week_id = ensure_dashboard(
        client, WEEK_NAME,
        "One FOM survey week: what people named, then how each media group covered one "
        "of its events, and the posts behind the numbers.",
        collection_id,
    )

    open_week = link(week_id, week="Week")
    place_cards(
        client, overview_id,
        [
            filter_parameter("area", "Area", values=snap.areas),
            filter_parameter("theme", "Theme", values=snap.themes),
        ],
        [
            Place(
                "**How Russian-language media groups covered the events people named in "
                "FOM's weekly survey, 2020–2025.** Click a week or an event to open it in "
                f"[{WEEK_NAME}](/dashboard/{week_id}); pick an Area or a Theme above to see "
                "how it was put together and what was measured inside it (with both "
                "picked, the theme decides).\n\n"
                "Survey values added over several events are **mentions per 100 "
                "respondents** — one person can name two events, so they are not a share "
                "of people. An event without a matched post set is **not measured yet**, "
                "never 0. Totals over several events count **each post once**. The news "
                f"data ends on **{NEWS_DATA_ENDS}**; nothing here describes anything later.",
                0, 0, 24, 3,
            ),
            Place(overview["weeks"], 0, 3, 6, 3),
            Place(overview["events"], 6, 3, 6, 3),
            Place(overview["measured"], 12, 3, 6, 3),
            Place(overview["posts"], 18, 3, 6, 3),
            Place(overview["heatmap"], 0, 6, 24, 10, clicks={"Week": open_week}),
            Place(overview["scope_weeks"], 0, 16, 10, 9, clicks={"Week": open_week}),
            Place(
                overview["wordings"], 10, 16, 14, 9,
                clicks={
                    "First named": link(week_id, week="First named", event="FOM wording"),
                    "Last named": link(week_id, week="Last named", event="FOM wording"),
                },
            ),
            Place(
                overview["coverage"], 0, 25, 24, 8,
                clicks={"Event": link(week_id, week="Week", event="FOM wording")},
            ),
        ],
    )

    pick_group = crossfilter(group="Media group")
    place_cards(
        client, week_id,
        [
            filter_parameter("week", "Week", values=snap.weeks, default=snap.default_week),
            filter_parameter("event", "Event"),
            filter_parameter("group", "Media group", values=GROUP_ORDER),
            filter_parameter("word", "Word"),
        ],
        [
            Place(
                f"**One FOM survey week.** Back to [{OVERVIEW_NAME}](/dashboard/{overview_id}). "
                "Click an event on the list to show its coverage; the Media group and Word "
                "filters narrow the words and posts. Three different zeros: **0 of N posts** "
                "(the group published and matched nothing), **not publishing in this window** "
                "(it published nothing at all), and **not measured yet** (nobody has built "
                "this event's matched post set).",
                0, 0, 24, 2,
            ),
            Place(
                week["header"], 0, 2, 24, 3,
                clicks={
                    name: link(week_id, week=name)
                    for name in ("‹ Previous survey week", "Next survey week ›",
                                 "‹ Measured coverage", "Measured coverage ›")
                },
            ),
            Place(
                week["list"], 0, 5, 14, 11,
                clicks={
                    "FOM wording": crossfilter(event="FOM wording"),
                    "Theme": link(overview_id, theme="Theme"),
                },
            ),
            Place(week["event"], 14, 5, 10, 11),
            Place(week["bars"], 0, 16, 12, 7, on_click=pick_group),
            Place(week["numbers"], 12, 16, 12, 7, clicks={"Media group": pick_group}),
            Place(week["daily"], 0, 23, 24, 6),
            Place(
                week["words"], 0, 29, 10, 10,
                # A word is counted within one group, so clicking it picks that group too.
                clicks={"Word or phrase": crossfilter(word="Word or phrase", group="Media group")},
            ),
            Place(week["posts"], 10, 29, 14, 10),
        ],
    )
    return overview_id, week_id


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

    snap = read_snapshot()

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

    print("Collection:")
    collection_id = ensure_collection(client)

    print("Database connection:")
    database_id = ensure_database(client)
    wait_for_tables(client, database_id)

    tags = {
        "area": template_tag("area", "Area"),
        "theme": template_tag("theme", "Theme"),
        "week": template_tag("week", "Week", default=snap.default_week),
        "event": template_tag("event", "Event"),
        "group": template_tag("group", "Media group"),
        "word": template_tag("word", "Word"),
    }
    overview = {card.key: card for card in overview_cards(snap)}
    week = {card.key: card for card in week_cards()}
    every_card = [*overview.values(), *week.values()]

    print("Questions:")
    ensure_cards(client, database_id, collection_id, every_card, tags)

    print("Dashboards:")
    overview_id, week_id = build_dashboards(client, snap, overview, week, collection_id)

    print("Retiring the single-page setup:")
    retire_old_setup(client, keep={card.name for card in every_card})

    print(f"\nDone. Open {METABASE_URL}/dashboard/{overview_id}")
    print(f"  and {METABASE_URL}/dashboard/{week_id}")


if __name__ == "__main__":
    main()
