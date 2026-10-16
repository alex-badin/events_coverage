#!/usr/bin/env python3
"""Export the dbt marts from the warehouse as one JSON file for the dashboard prototype.

The prototype dashboard is a single self-contained HTML file, so it cannot query the
warehouse itself — this script hands it a snapshot of exactly the mart tables a
Metabase dashboard would read live. When Metabase replaces the prototype, this script
stops being needed; nothing downstream of the marts depends on it.

Usage:
    .venv/bin/python scripts/export_dashboard_data.py

Writes outputs/dashboard_exports/dashboard_data.json.
"""

from __future__ import annotations

import ast
import json
from datetime import date, datetime
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_DB = PROJECT_ROOT / "data" / "warehouse" / "events.duckdb"
EXPORT_DIR = PROJECT_ROOT / "outputs" / "dashboard_exports"
EXPORT_JSON = EXPORT_DIR / "dashboard_data.json"

# The order media groups appear in, and therefore which colour each one keeps across
# every chart. Fixed here rather than derived from the data, because a group's colour
# must not change when a different event puts a different group on top.
GROUP_ORDER = [
    "State agencies",
    "Federal TV and state broadcasters",
    "Pro-government online media",
    "Mainstream business and general media",
    "Independent and exile media",
    "War and military channels",
]

QUERIES = {
    # The time axis: one row per calendar week, with has_survey marking the weeks FOM
    # published a list. Weeks without a survey are gaps on the page, not zeros.
    "weeks": """
        select * from survey_weeks
        order by week_start
    """,
    # Every row of every weekly survey list, with its theme and whether coverage was
    # measured for it.
    "week_events": """
        select
            event_id, fom_year, fom_week, week_start, event_name, event_kind,
            attention_percentage, quote_examples, rank_in_week,
            theme_id, umbrella_id, coverage_status, event_slug, event_label_en,
            matched_posts
        from week_events
        order by week_start, rank_in_week nulls last, attention_percentage desc
    """,
    # The theme list with its definitions, for labels and for the "how this theme was
    # put together" table.
    "themes": """
        select * from fom_themes
        order by umbrella_order, theme_order
    """,
    # How much of each week's survey answers went to each theme.
    "theme_weeks": """
        select
            theme_id, umbrella_id, week_start, attention_sum, n_events,
            top_event_name, top_event_share, n_top_events, n_measured_events
        from theme_week_attention
        order by week_start, theme_id
    """,
    # Coverage added up per theme, per umbrella and overall, each post counted once.
    "scope_coverage": """
        select * from theme_group_coverage
        order by scope_type, scope_id, media_group
    """,
    # One row per measured event: build settings and the two trust checks.
    "events": """
        select * from event_overview
        order by match_start
    """,
    # One row per media group per measured event.
    "groups": """
        select * from event_group_coverage
        order by event_id, matched_posts desc
    """,
    # One row per media group per day of each event window, zeros included.
    "daily": """
        select event_id, media_group, coverage_date, matched_posts
        from event_group_daily
        order by event_id, media_group, coverage_date
    """,
    # The words that separate one group's coverage from the others' (single words only,
    # the top eight per group).
    "terms": """
        select
            event_id, media_group, term_label, posts_with_term, group_posts,
            share_elsewhere, distinctiveness_rank,
            -- The exact posts the count is based on, so clicking a word shows that set
            -- and not a re-derived approximation of it.
            post_keys
        from event_group_terms
        where term_type = 'word' and distinctiveness_rank <= 8
        order by event_id, media_group, distinctiveness_rank
    """,
    # One row per matched post, for the drill-down.
    "posts": """
        select
            event_id, media_group, source_name, message_id, published_at,
            is_digest, views, forwards, rerank_score, post_text
        from event_message_detail
        order by event_id, rerank_score desc
    """,
}


def to_plain(value):
    """Turn warehouse values into something json.dump can write."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return None
    # DuckDB hands back numpy scalars for numeric columns.
    if hasattr(value, "item"):
        return value.item()
    return value


def fetch(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    columns = [description[0] for description in cursor.description]
    return [
        {column: to_plain(value) for column, value in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]


def parse_quotes(text):
    """FOM quote examples are stored as the text of a Python list; hand the page a real list."""
    if not text:
        return []
    try:
        quotes = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    return [str(q).strip().strip("«»") for q in quotes]


def main() -> None:
    if not WAREHOUSE_DB.is_file():
        raise FileNotFoundError(
            f"No warehouse at {WAREHOUSE_DB}. Run scripts/load_warehouse.py, then dbt build."
        )

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        payload = {name: fetch(con, sql) for name, sql in QUERIES.items()}
        snapshot_end = con.execute("select max(activity_date) from stg_source_activity").fetchone()[0]
    finally:
        con.close()

    for row in payload["week_events"]:
        row["quotes"] = parse_quotes(row.pop("quote_examples"))

    payload["meta"] = {
        "group_order": GROUP_ORDER,
        # The last day the news corpus has posts for. Nothing on the page may read as
        # current after it.
        "snapshot_end": snapshot_end.isoformat(),
        "row_counts": {name: len(rows) for name, rows in payload.items()},
        # Left blank deliberately: an export timestamp would make the file differ on
        # every run and show up as a change in git even when the numbers are identical.
        "source": "data/warehouse/events.duckdb, dbt marts",
    }

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    size_mb = EXPORT_JSON.stat().st_size / 1_000_000
    for name, rows in payload.items():
        if isinstance(rows, list):
            print(f"{name:15} {len(rows):>6,} rows")
    print(f"\nWrote {EXPORT_JSON.relative_to(PROJECT_ROOT)}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
