"""The code location Dagster loads for the Events Coverage project."""

import dagster as dg
from dagster_dbt import DbtCliResource

from events_coverage.defs import (
    DBT_PROJECT,
    events_coverage_dbt_assets,
    metabase_snapshot,
    raw_warehouse_tables,
    static_refresh_job,
    validated_static_inputs,
)

defs = dg.Definitions(
    assets=[
        validated_static_inputs,
        raw_warehouse_tables,
        events_coverage_dbt_assets,
        metabase_snapshot,
    ],
    jobs=[static_refresh_job],
    resources={
        "dbt": DbtCliResource(
            project_dir=DBT_PROJECT.project_dir,
            profiles_dir=DBT_PROJECT.profiles_dir,
        )
    },
)
