#!/usr/bin/env python3
"""Load raw source tables into the local DuckDB warehouse.

Creates (or updates) `data/warehouse/events.duckdb` with the raw tables that the dbt
project reads. Re-running is safe: each table is replaced, never appended, so this is
always a full refresh of the raw layer.

Usage:
    .venv/bin/python scripts/load_warehouse.py           # load, then print what is there
    .venv/bin/python scripts/load_warehouse.py --show    # only print, load nothing

Raw project inputs are opened read-only and never modified.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FOM_EVENTS_CSV = PROJECT_ROOT / "fom_events" / "processed_events" / "events_table.csv"
WAREHOUSE_DB = PROJECT_ROOT / "data" / "warehouse" / "events.duckdb"

RAW_SCHEMA = "raw"


def require_readable(path: Path) -> None:
    """Fail early and clearly if an input file is missing or unreadable."""
    if not path.is_file():
        raise FileNotFoundError(f"Missing required input: {path}")
    with path.open("rb") as file:
        file.read(1)


def load_fom_events(con: duckdb.DuckDBPyConnection) -> None:
    """Copy the cleaned FOM weekly event table into raw.fom_events.

    Column types are left to DuckDB's CSV type detection; the dbt staging model is
    where types and names get fixed deliberately.
    """
    require_readable(FOM_EVENTS_CSV)
    con.execute(
        f"""
        create or replace table {RAW_SCHEMA}.fom_events as
        select * from read_csv_auto('{FOM_EVENTS_CSV.as_posix()}', header = true)
        """
    )


def describe_raw_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Print every table in the raw schema with its row count and column types."""
    tables = [
        row[0]
        for row in con.execute(
            "select table_name from information_schema.tables "
            "where table_schema = ? order by table_name",
            [RAW_SCHEMA],
        ).fetchall()
    ]
    if not tables:
        print(f"No tables in schema '{RAW_SCHEMA}' yet.")
        return

    for table in tables:
        rows = con.execute(f"select count(*) from {RAW_SCHEMA}.{table}").fetchone()[0]
        print(f"\n{RAW_SCHEMA}.{table}  —  {rows:,} rows")
        for name, dtype, *_ in con.execute(f"describe {RAW_SCHEMA}.{table}").fetchall():
            print(f"    {name:<12} {dtype}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show",
        action="store_true",
        help="only print what is already in the warehouse, load nothing",
    )
    args = parser.parse_args()

    WAREHOUSE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WAREHOUSE_DB))
    try:
        if not args.show:
            con.execute(f"create schema if not exists {RAW_SCHEMA}")
            load_fom_events(con)
        describe_raw_tables(con)
    finally:
        con.close()

    size_mb = WAREHOUSE_DB.stat().st_size / 1_000_000
    print(f"\nWarehouse file: {WAREHOUSE_DB.relative_to(PROJECT_ROOT)}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
