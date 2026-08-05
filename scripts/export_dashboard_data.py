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
    # One row per event: the list the dashboard opens with, plus the public-attention
    # against coverage-volume comparison from the gaps mart.
    "events": """
        select
            overview.*,
            gaps.attention_position,
            gaps.volume_position,
            gaps.attention_minus_volume,
            gaps.gap_direction
        from event_overview as overview
        left join event_coverage_gaps as gaps using (event_id)
        order by overview.match_start
    """,
    # One row per media group per event.
    "groups": """
        select * from event_group_coverage
        order by event_slug, matched_posts desc
    """,
    # One row per media group per day of each event window, zeros included.
    "daily": """
        select * from event_group_daily
        order by event_slug, media_group, coverage_date
    """,
    # One row per media group per event, for comparing events with each other.
    "resonance": """
        select * from event_group_resonance
        order by event_slug, media_group
    """,
    # The words and phrases that separate one group's coverage from the others'.
    # Capped at the top few per group so the exported file stays small; the full table
    # lives in the warehouse.
    "terms": """
        select
            event_slug,
            media_group,
            term_type,
            term_key,
            term_label,
            posts_with_term,
            sources_with_term,
            group_posts,
            share_in_group,
            share_elsewhere,
            distinctiveness,
            distinctiveness_rank,
            -- The exact posts the count is based on, so clicking a word shows that set and
            -- not a re-derived approximation of it.
            post_keys
        from event_group_terms
        where distinctiveness_rank <= 8
        order by event_slug, media_group, term_type, distinctiveness_rank
    """,
    # One row per matched post, for the drill-down.
    "posts": """
        select
            event_slug,
            media_group,
            source_name,
            message_id,
            published_at,
            published_date,
            days_from_window_start,
            is_digest,
            views,
            forwards,
            rerank_score,
            keyword_match,
            post_text
        from event_message_detail
        order by event_slug, rerank_score desc
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


def main() -> None:
    if not WAREHOUSE_DB.is_file():
        raise FileNotFoundError(
            f"No warehouse at {WAREHOUSE_DB}. Run scripts/load_warehouse.py, then dbt build."
        )

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        payload = {name: fetch(con, sql) for name, sql in QUERIES.items()}
    finally:
        con.close()

    payload["meta"] = {
        "group_order": GROUP_ORDER,
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
            print(f"{name:8} {len(rows):>6,} rows")
    print(f"\nWrote {EXPORT_JSON.relative_to(PROJECT_ROOT)}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
