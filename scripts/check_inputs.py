#!/usr/bin/env python3
"""Check that the current local project inputs are readable."""

from __future__ import annotations

import csv
import argparse
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

NEWS_DB = PROJECT_ROOT / "news_data" / "ask_media_unified_messages_20260604.db"
NEWS_README = PROJECT_ROOT / "news_data" / "ask_media_unified_messages_20260604_README.md"
NEWS_STATS = PROJECT_ROOT / "news_data" / "ask_media_unified_basic_stats_20260604.md"
FOM_EVENTS = PROJECT_ROOT / "fom_events" / "processed_events" / "events_table.csv"


def require_readable(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Required path is not a file: {path}")
    with path.open("rb") as file:
        file.read(1)


def check_news_database(*, full: bool) -> None:
    require_readable(NEWS_DB)

    with sqlite3.connect(NEWS_DB) as conn:
        table_exists = conn.execute(
            """
            select 1
            from sqlite_master
            where type = 'table'
              and name = 'unified_messages'
            """
        ).fetchone()
        if not table_exists:
            raise RuntimeError("SQLite database is missing the unified_messages table")

        row_count = conn.execute("select count(*) from unified_messages").fetchone()[0]
        source_count = conn.execute("select count(distinct source) from unified_messages").fetchone()[0]
        min_date, max_date = conn.execute(
            "select min(date), max(date) from unified_messages"
        ).fetchone()

        quick_check = "skipped"
        if full:
            quick_check = conn.execute("pragma quick_check").fetchone()[0]
            if quick_check != "ok":
                raise RuntimeError(f"SQLite quick_check failed: {quick_check}")

    print("News database")
    print(f"  path: {NEWS_DB.relative_to(PROJECT_ROOT)}")
    print(f"  database open: ok")
    print(f"  full quick check: {quick_check}")
    print(f"  rows: {row_count:,}")
    print(f"  sources: {source_count:,}")
    print(f"  date range: {min_date} to {max_date}")


def check_fom_events() -> None:
    require_readable(FOM_EVENTS)

    row_count = 0
    blank_events = 0
    missing_percentages = 0
    years: dict[str, int] = {}

    with FOM_EVENTS.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        expected_columns = {"date", "year", "week", "event", "description", "percentage"}
        missing_columns = expected_columns - set(reader.fieldnames or [])
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise RuntimeError(f"FOM event table is missing columns: {missing}")

        for row in reader:
            row_count += 1
            year = row["year"]
            years[year] = years.get(year, 0) + 1
            if not row["event"].strip():
                blank_events += 1
            if not row["percentage"].strip():
                missing_percentages += 1

    print("\nFOM events")
    print(f"  path: {FOM_EVENTS.relative_to(PROJECT_ROOT)}")
    print(f"  rows: {row_count:,}")
    print(f"  blank event names: {blank_events:,}")
    print(f"  missing percentages: {missing_percentages:,}")
    print("  rows by year:")
    for year in sorted(years):
        print(f"    {year}: {years[year]:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run SQLite quick_check. This can take about a minute on the current database.",
    )
    args = parser.parse_args()

    for path in [NEWS_README, NEWS_STATS, FOM_EVENTS]:
        require_readable(path)

    check_news_database(full=args.full)
    check_fom_events()

    print("\nInput check completed.")


if __name__ == "__main__":
    main()
