#!/usr/bin/env python3
"""Copy the warehouse to the file Metabase reads.

Metabase gets a copy, not the working warehouse, for one practical reason: DuckDB allows a
single writer at a time, and `dbt build` rewrites the warehouse file on every run. If
Metabase were holding the working file open, a dbt run would either fail or leave Metabase
pointing at a file that had been replaced underneath it.

So the flow is the same one a real setup uses: transformations write the warehouse, then a
publish step hands a finished snapshot to the reporting layer.

Usage:
    .venv/bin/python scripts/publish_warehouse_for_metabase.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_DB = PROJECT_ROOT / "data" / "warehouse" / "events.duckdb"
SERVED_DIR = PROJECT_ROOT / "metabase" / "data"
SERVED_DB = SERVED_DIR / "events.duckdb"

# The marts the reporting layer is allowed to see. Staging and intermediate models are
# working steps, not answers, and putting them in front of a dashboard user invites
# charts built on half-finished numbers.
PUBLISHED_MARTS = [
    "event_overview",
    "event_group_coverage",
    "event_group_resonance",
    "event_coverage_gaps",
    "event_group_daily",
    "event_group_terms",
    "event_message_detail",
]


def main() -> None:
    if not WAREHOUSE_DB.is_file():
        raise FileNotFoundError(
            f"No warehouse at {WAREHOUSE_DB}. Run scripts/load_warehouse.py, then dbt build."
        )

    SERVED_DIR.mkdir(parents=True, exist_ok=True)

    # Copy first, then prune, so the working warehouse is never modified.
    shutil.copy2(WAREHOUSE_DB, SERVED_DB)

    con = duckdb.connect(str(SERVED_DB))
    try:
        # Views and tables have to be dropped with the matching statement, so the type is
        # read from the catalogue rather than guessed.
        existing = {
            name: kind
            for name, kind in con.execute(
                "select table_name, table_type from information_schema.tables "
                "where table_schema = 'main'"
            ).fetchall()
        }
        missing = [name for name in PUBLISHED_MARTS if name not in existing]
        if missing:
            raise RuntimeError(
                "These marts are not in the warehouse — run dbt build first: "
                + ", ".join(missing)
            )

        for name in sorted(set(existing) - set(PUBLISHED_MARTS)):
            keyword = "view" if existing[name] == "VIEW" else "table"
            con.execute(f'drop {keyword} if exists main."{name}" cascade')

        # The raw schema holds full copies of the source files; the reporting layer has no
        # reason to see them.
        con.execute("drop schema if exists raw cascade")
        con.execute("checkpoint")

        for name in PUBLISHED_MARTS:
            rows = con.execute(f"select count(*) from {name}").fetchone()[0]
            print(f"  {name:24} {rows:>8,} rows")
    finally:
        con.close()

    size_mb = SERVED_DB.stat().st_size / 1_000_000
    print(f"\nPublished {SERVED_DB.relative_to(PROJECT_ROOT)}  ({size_mb:.1f} MB)")
    print("Metabase reads this file at /data/events.duckdb inside its container.")


if __name__ == "__main__":
    main()
