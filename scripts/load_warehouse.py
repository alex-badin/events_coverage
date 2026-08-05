#!/usr/bin/env python3
"""Load raw source tables into the local DuckDB warehouse.

Creates (or updates) `data/warehouse/events.duckdb` with the raw tables that the dbt
project reads. Re-running is safe: each table is replaced, never appended, so this is
always a full refresh of the raw layer.

Usage:
    .venv/bin/python scripts/load_warehouse.py           # load, then print what is there
    .venv/bin/python scripts/load_warehouse.py --show    # only print, load nothing

Raw project inputs are opened read-only and never modified.

What gets loaded
----------------
raw.fom_events         The cleaned FOM weekly event table (one row per event per week).
raw.event_matches      One row per news message matched to an event, for the event
                       datasets listed in EVENT_SLUGS below.
raw.event_datasets     One row per loaded event dataset: the run settings and counts
                       recorded in its manifest file (which retriever, which
                       thresholds, how many messages were kept).
raw.media_groups       The source -> media group map from configs/media_groups.yaml.
                       In-scope sources only: the 56 that belong to a group.
raw.archived_sources   The sources deliberately left out of the study, with the reason.
                       Loaded for provenance, so the dashboard can state what was
                       excluded; no other raw table contains their rows.
raw.source_day_activity  Posts per source per calendar day across the whole news
                       corpus. This is the denominator that separates "this source
                       said nothing about the event" from "this source was not
                       publishing at all that week".

Archived sources are dropped here, at load time, rather than by editing the event dataset
files in data/processed/. Those files are pipeline outputs whose row counts are recorded in
their own manifests; rewriting them would leave each manifest's `kept` count disagreeing
with its file. The exclusion is therefore applied to raw.event_matches and
raw.source_day_activity, and the number of rows dropped is printed on every run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from events_coverage.matching import load_archived_sources  # noqa: E402

FOM_EVENTS_CSV = PROJECT_ROOT / "fom_events" / "processed_events" / "events_table.csv"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MEDIA_GROUPS_YAML = PROJECT_ROOT / "configs" / "media_groups.yaml"
NEWS_SQLITE = PROJECT_ROOT / "news_data" / "ask_media_unified_messages_20260604.db"
WAREHOUSE_DB = PROJECT_ROOT / "data" / "warehouse" / "events.duckdb"

RAW_SCHEMA = "raw"

# The event datasets that are complete and built with the current retriever.
#
# Deliberately an explicit list, not a folder scan: `data/processed/` also holds
# known-incomplete pilot leftovers. Excluded on purpose —
#   *_cohere_archived        built on the archived sparse Cohere embeddings (incomplete),
#   the slugs without `_qwen3`  earlier builds whose first-stage search could only see
#                            part of each window; every one of them was rebuilt on the
#                            Qwen3 sidecar on 2026-08-03 and the rebuild is listed here,
#   event_prices_2025w11*    «Рост цен, тарифов» — rebuilt the same way and kept 0 posts
#                            at the standard relevance cut-off of 0.35 (highest rerank
#                            score in its 3,000 candidates was under 0.30), so there is
#                            nothing to show. The earlier build only had rows because it
#                            used a cut-off of 0.10.
# See the cautions in AGENTS.md.
EVENT_SLUGS = [
    "event_dc_aircrash_2025w05_qwen3",
    "event_kursk_2025w11_qwen3",
    "event_putin_trump_call_2025w08_qwen3",
    "event_trump_zelensky_2025w10_qwen3",
    "event_us_russia_contacts_2025w09_qwen3",
]

# Columns kept from each event dataset CSV. The heavy text stays: it is only a few
# thousand rows in total, and the dashboard drill-down shows the posts themselves.
MATCH_COLUMNS = [
    "source",
    "message_id",
    "date",
    "is_digest",
    "summary",
    "original_message",
    "views",
    "forwards",
    "cosine_max",
    "rerank_score",
    "keyword_match",
]


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


def archived_sql_list() -> str:
    """The archived sources as a SQL `in (...)` list, ready to drop from a query."""
    archived = sorted(load_archived_sources())
    if not archived:
        return "('')"
    quoted = ", ".join("'" + source.replace("'", "''") + "'" for source in archived)
    return f"({quoted})"


def load_event_matches(con: duckdb.DuckDBPyConnection) -> None:
    """Stack the per-event matched-message files into one raw table.

    Each event dataset is a separate CSV with no event column of its own, so the
    event name, year and week come from the matching manifest file and are added
    here. That is what makes a single table with one row per message per event.

    Posts from archived sources are dropped, so every downstream count is over
    in-scope sources only.
    """
    selects = []
    for slug in EVENT_SLUGS:
        dataset_csv = PROCESSED_DIR / f"{slug}_dataset.csv"
        manifest_json = PROCESSED_DIR / f"{slug}_manifest.json"
        require_readable(dataset_csv)
        require_readable(manifest_json)

        event = json.loads(manifest_json.read_text(encoding="utf-8"))["event"]
        name_sql = event["name"].replace("'", "''")
        columns = ", ".join(MATCH_COLUMNS)
        selects.append(
            f"""
            select
                '{slug}'            as event_slug,
                '{name_sql}'        as event_name,
                {event["year"]}     as fom_year,
                {event["week"]}     as fom_week,
                {columns}
            from read_csv_auto('{dataset_csv.as_posix()}', header = true)
            where source not in {archived_sql_list()}
            """
        )

    con.execute(
        f"create or replace table {RAW_SCHEMA}.event_matches as "
        + "\nunion all by name\n".join(selects)
    )

    # Say out loud how many matched posts the archiving removed, so the number is never
    # a silent difference between two runs.
    dropped = 0
    for slug in EVENT_SLUGS:
        dataset_csv = PROCESSED_DIR / f"{slug}_dataset.csv"
        dropped += con.execute(
            f"select count(*) from read_csv_auto('{dataset_csv.as_posix()}', header = true) "
            f"where source in {archived_sql_list()}"
        ).fetchone()[0]
    print(f"    archived sources excluded: {dropped:,} matched posts")


def load_event_datasets(con: duckdb.DuckDBPyConnection) -> None:
    """Record how each event dataset was built, one row per event.

    These are the run settings from the manifest files: which embedding model
    retrieved the candidates, which rerank threshold kept them, how large the
    candidate pool was. Keeping them in the warehouse means the dashboard can show
    the provenance of a number instead of asking the reader to trust it.
    """
    rows = []
    for slug in EVENT_SLUGS:
        manifest = json.loads(
            (PROCESSED_DIR / f"{slug}_manifest.json").read_text(encoding="utf-8")
        )
        # Every dataset here was built before the 2026-08-03 decision to archive the
        # out-of-scope sources, so its manifest `kept` count still includes their posts.
        # Count them per event, so "the pipeline said N, the SQL says M" stays an exact
        # check instead of being relaxed to a tolerance.
        dataset_csv = PROCESSED_DIR / f"{slug}_dataset.csv"
        archived_excluded = con.execute(
            f"select count(*) from read_csv_auto('{dataset_csv.as_posix()}', header = true) "
            f"where source in {archived_sql_list()}"
        ).fetchone()[0]
        event = manifest["event"]
        window = manifest["window"]
        models = manifest["models"]
        params = manifest["params"]
        counts = manifest["counts"]
        rows.append(
            {
                "event_slug": slug,
                "event_name": event["name"],
                "fom_year": event["year"],
                "fom_week": event["week"],
                "fom_percentage": event.get("fom_percentage"),
                "fom_quotes": json.dumps(event.get("quotes", []), ensure_ascii=False),
                "built_at": manifest.get("generated_at"),
                "match_start": window["match_start"],
                "match_end_exclusive": window["match_end_exclusive"],
                "retriever": models.get("retriever", "cohere"),
                "embed_model": models.get("embed_model"),
                "rerank_model": models.get("rerank_model"),
                "top_k": params.get("top_k"),
                "rerank_threshold": params.get("rerank_threshold"),
                "candidates": counts.get("candidates"),
                "kept": counts.get("kept"),
                "archived_posts_excluded": archived_excluded,
                # How many posts in the window had an embedding vector at all, and were
                # therefore even eligible to be found. Where this is well below the
                # number of posts actually published in the window, the coverage counts
                # are an undercount and a silent group may just be an unsearchable one.
                "embedded_pool": counts.get("embedded_pool"),
            }
        )

    con.register("event_datasets_df", _as_relation(con, rows))
    con.execute(
        f"create or replace table {RAW_SCHEMA}.event_datasets as "
        f"select * from event_datasets_df"
    )
    con.unregister("event_datasets_df")


def load_media_groups(con: duckdb.DuckDBPyConnection) -> None:
    """Flatten the `groups:` block of configs/media_groups.yaml into one row per source.

    In-scope sources only. Sources under `archived:` are handled by
    `load_archived_sources_table` and are absent from every other raw table, so there is
    no longer an "ungrouped" bucket to show in the dashboard.
    """
    require_readable(MEDIA_GROUPS_YAML)
    config = yaml.safe_load(MEDIA_GROUPS_YAML.read_text(encoding="utf-8"))

    rows = []
    for group_key, group in (config.get("groups") or {}).items():
        for source in group.get("sources") or []:
            rows.append(
                {
                    "source": source,
                    "group_key": group_key,
                    "group_label": group["label"],
                    "is_grouped": True,
                }
            )

    con.register("media_groups_df", _as_relation(con, rows))
    con.execute(
        f"create or replace table {RAW_SCHEMA}.media_groups as "
        f"select * from media_groups_df"
    )
    con.unregister("media_groups_df")


def load_archived_sources_table(con: duckdb.DuckDBPyConnection) -> None:
    """Record the sources left out of the study, and why.

    Nothing downstream joins to this table; it is here so the exclusion is a fact in the
    warehouse rather than only a comment in a config file, and so the dashboard can name
    what it left out.
    """
    require_readable(MEDIA_GROUPS_YAML)
    config = yaml.safe_load(MEDIA_GROUPS_YAML.read_text(encoding="utf-8"))

    rows = [
        {"source": source, "archive_reason": reason_key.removeprefix("reason_")}
        for reason_key, sources in (config.get("archived") or {}).items()
        for source in sources or []
    ]

    con.register("archived_sources_df", _as_relation(con, rows))
    con.execute(
        f"create or replace table {RAW_SCHEMA}.archived_sources as "
        f"select * from archived_sources_df"
    )
    con.unregister("archived_sources_df")


def load_source_day_activity(con: duckdb.DuckDBPyConnection) -> None:
    """Count posts per source per day across the whole news corpus.

    Read straight out of the SQLite file with DuckDB's sqlite reader, so nothing is
    copied or migrated. The result is small (one row per source per day) and it is
    what lets a later model say whether a silent source was silent on this event or
    absent from the corpus altogether.

    Archived sources are excluded here as well as from the matched sets. If they were
    left in, "sources publishing anything at all during the window" would keep counting
    channels the study no longer looks at, and every coverage rate would read low.
    """
    require_readable(NEWS_SQLITE)
    con.execute("install sqlite")
    con.execute("load sqlite")
    con.execute(
        f"""
        create or replace table {RAW_SCHEMA}.source_day_activity as
        select
            source,
            -- The date column is text like '2025-03-20 11:50:50+00:00'; the first
            -- ten characters are the calendar day in UTC.
            try_cast(substr(date, 1, 10) as date)  as activity_date,
            count(*)                              as post_count
        from sqlite_scan('{NEWS_SQLITE.as_posix()}', 'unified_messages')
        where date is not null
          and source not in {archived_sql_list()}
        group by 1, 2
        """
    )


def _as_relation(con: duckdb.DuckDBPyConnection, rows: list[dict]):
    """Turn a list of dictionaries into something DuckDB can select from."""
    import pandas as pd

    return con.from_df(pd.DataFrame(rows))


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
            print(f"    {name:<22} {dtype}")


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
            load_event_matches(con)
            load_event_datasets(con)
            load_media_groups(con)
            load_archived_sources_table(con)
            load_source_day_activity(con)
        describe_raw_tables(con)
    finally:
        con.close()

    size_mb = WAREHOUSE_DB.stat().st_size / 1_000_000
    print(f"\nWarehouse file: {WAREHOUSE_DB.relative_to(PROJECT_ROOT)}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
