"""Dagster assets for rebuilding the current static data product.

This first orchestration layer wraps the commands that already define a trusted build:

    validate inputs -> load raw DuckDB tables -> dbt models/tests -> Metabase snapshot

Future download, text-processing, embedding, and matching assets belong upstream of this
graph. They are intentionally absent until the static graph is understood and dependable.
"""

import subprocess
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import dagster as dg
import duckdb
from dagster import AssetExecutionContext, MaterializeResult
from dagster_dbt import (
    DagsterDbtTranslator,
    DagsterDbtTranslatorSettings,
    DbtCliResource,
    DbtProject,
    dbt_assets,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt"
WAREHOUSE_DB = PROJECT_ROOT / "data" / "warehouse" / "events.duckdb"

DBT_PROJECT = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    profiles_dir=DBT_PROJECT_DIR,
)
# During local development, Dagster regenerates dbt/target/manifest.json when the dbt
# project changes.
# The manifest is how Dagster learns the dbt model names and dependencies without duplicating
# them in Python.
DBT_PROJECT.prepare_if_dev()

RAW_TABLE_DESCRIPTIONS = {
    "fom_events": "Cleaned FOM weekly event table.",
    "event_matches": "Current matched post sets for the five loaded pilot events.",
    "event_datasets": "Matching model, threshold, window, and row-count provenance.",
    "media_groups": "In-scope source-to-media-group mapping.",
    "archived_sources": "Sources excluded from the analytical comparison, with reasons.",
    "source_day_activity": "All published posts per source and day, used as a denominator.",
}

REPORTING_MARTS = (
    "event_overview",
    "event_group_coverage",
    "event_group_resonance",
    "event_coverage_gaps",
    "event_group_daily",
    "event_group_terms",
    "event_message_detail",
)


def _run_project_command(
    context: AssetExecutionContext,
    command: Sequence[str],
) -> None:
    """Run one existing project command and copy its output into the Dagster run log."""
    context.log.info("Running: %s", " ".join(command))
    process = subprocess.Popen(  # noqa: S603 - command is a fixed internal sequence
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        context.log.info(line.rstrip())

    return_code = process.wait()
    if return_code:
        raise dg.Failure(
            description=f"Command failed with exit code {return_code}: {' '.join(command)}"
        )


@dg.asset(
    key=dg.AssetKey(["source", "validated_static_inputs"]),
    group_name="source_inputs",
    kinds={"csv", "sqlite"},
    description=(
        "A successful readability check of the local posts database and FOM event table. "
        "This asset changes no source data."
    ),
)
def validated_static_inputs(context: AssetExecutionContext) -> MaterializeResult:
    """Fail before warehouse writes if either primary input cannot be read."""
    _run_project_command(
        context,
        [sys.executable, str(PROJECT_ROOT / "scripts" / "check_inputs.py")],
    )
    return dg.MaterializeResult(
        metadata={
            "posts_database": dg.MetadataValue.path(
                str(PROJECT_ROOT / "news_data" / "ask_media_unified_messages_20260604.db")
            ),
            "fom_events": dg.MetadataValue.path(
                str(PROJECT_ROOT / "fom_events" / "processed_events" / "events_table.csv")
            ),
        }
    )


@dg.multi_asset(
    name="raw_warehouse_tables",
    specs=[
        dg.AssetSpec(
            key=dg.AssetKey(["raw", table_name]),
            description=description,
            group_name="warehouse_load",
            kinds={"duckdb"},
            deps=[validated_static_inputs],
        )
        for table_name, description in RAW_TABLE_DESCRIPTIONS.items()
    ],
    can_subset=False,
)
def raw_warehouse_tables(
    context: AssetExecutionContext,
) -> Iterator[MaterializeResult]:
    """Run the existing full-refresh loader once and report each raw table separately."""
    _run_project_command(
        context,
        [sys.executable, str(PROJECT_ROOT / "scripts" / "load_warehouse.py")],
    )

    connection = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        for table_name in RAW_TABLE_DESCRIPTIONS:
            row_count = connection.execute(
                f'select count(*) from raw."{table_name}"'  # noqa: S608 - fixed table names
            ).fetchone()[0]
            yield dg.MaterializeResult(
                asset_key=dg.AssetKey(["raw", table_name]),
                metadata={
                    "rows": row_count,
                    "warehouse": dg.MetadataValue.path(str(WAREHOUSE_DB)),
                },
            )
    finally:
        connection.close()


@dbt_assets(
    manifest=DBT_PROJECT.manifest_path,
    project=DBT_PROJECT,
    name="events_coverage_dbt_assets",
    # Without this, dbt tests declared on a source (raw.media_groups) still run but are
    # logged only as observations, not as asset checks on the raw asset.
    dagster_dbt_translator=DagsterDbtTranslator(
        settings=DagsterDbtTranslatorSettings(enable_source_tests_as_checks=True)
    ),
)
def events_coverage_dbt_assets(
    context: AssetExecutionContext,
    dbt: DbtCliResource,
):
    """Expose every dbt seed and model as an asset, then run dbt models and tests."""
    yield from dbt.cli(["build"], context=context).stream()


@dg.asset(
    key=dg.AssetKey(["reporting", "metabase_snapshot"]),
    deps=[dg.AssetKey(mart) for mart in REPORTING_MARTS],
    group_name="reporting",
    kinds={"duckdb"},
    description="Pruned copy of the finished warehouse that the local Metabase reads.",
)
def metabase_snapshot(context: AssetExecutionContext) -> MaterializeResult:
    """Publish a read-only reporting copy so Metabase never locks the working warehouse."""
    output_path = PROJECT_ROOT / "metabase" / "data" / "events.duckdb"
    _run_project_command(
        context,
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "publish_warehouse_for_metabase.py"),
        ],
    )
    return dg.MaterializeResult(
        metadata={
            "path": dg.MetadataValue.path(str(output_path)),
            "size_bytes": output_path.stat().st_size,
        }
    )


static_refresh_job = dg.define_asset_job(
    name="static_refresh",
    selection=dg.AssetSelection.assets(
        validated_static_inputs,
        raw_warehouse_tables,
        events_coverage_dbt_assets,
        metabase_snapshot,
    ),
    description=(
        "Manually rebuild the current static Events Coverage product from readable local inputs."
    ),
)
