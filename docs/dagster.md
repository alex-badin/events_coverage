# Dagster — first static orchestration layer

## What Dagster does here

Dagster is the orchestrator. It answers four operational questions:

1. What data products does this project create?
2. What does each one depend on?
3. Which ones were rebuilt successfully, and when?
4. Where did a failed refresh stop?

It does not replace the existing tools. Python still loads the raw tables and creates the
reporting files. dbt still owns the SQL models and their tests. Dagster calls them in the
right order and records the result as one visible graph.

The first graph is deliberately static:

```text
validated local inputs
        |
        v
seven raw DuckDB tables
        |
        v
dbt seed -> staging models -> intermediate models -> marts + tests
        |
        v
Metabase DuckDB snapshot
```

There is no schedule yet and no post download, event download, summarization, embedding,
or matching run. The current source files and matched event datasets remain the inputs.

## The five Dagster ideas used in this project

**Asset.** A data product we want to exist, such as `raw/fom_events`, the dbt model
`event_group_coverage`, or `reporting/metabase_snapshot`. An asset is not just a script
step: its name describes the result of the work.

**Materialization.** One successful production of an asset. A materialization records when
the work ran and can carry useful facts. The raw table assets record row counts; the file
assets record paths and file sizes.

**Dependency.** The reason Dagster knows the order. For example, `stg_events` depends on
`raw/fom_events`, while the Metabase snapshot depends on the published marts.

**Job.** A named selection of assets to run. `static_refresh` selects the whole current
graph. The graph defines the order; the job does not contain a second hand-written sequence.

**Resource.** Runtime access to an external tool or service. The first resource is dbt's
command runner, configured with this repository's `dbt/` project and local profile.

## How dbt becomes part of the graph

dbt writes `dbt/target/manifest.json` when it parses the project. The manifest lists every
model, seed, source, test, and dependency. The Dagster dbt integration reads it and creates
Dagster assets from the dbt nodes. This is why the SQL lineage is not copied into Python.

During local development, `DBT_PROJECT.prepare_if_dev()` refreshes the manifest when the dbt
project changes. When a dbt asset is materialized, Dagster runs `dbt build`; model results
become materializations and dbt tests appear as asset checks in the interface.

All 90 dbt data tests appear as asset checks. Two kinds need explicit wiring, or Dagster
runs them but logs only an observation: tests declared on a source (the two on
`raw.media_groups`) need `enable_source_tests_as_checks` in the dbt translator, and a
singular test that reads more than one model needs a `meta.dagster.ref` config naming the
model to attach it to (see `assert_matched_posts_match_the_build_manifests.sql`). The two
dbt unit tests also run inside `dbt build`, but Dagster does not show them as checks; their
result is only in the run log.

The five dbt source nodes use keys such as `raw/fom_events`. The Python warehouse loader
materializes raw assets with those same keys, joining the Python and dbt halves into one
graph.

## Install and open the local interface

Run these commands from the repository root:

```sh
uv sync
mkdir -p .dagster
DAGSTER_HOME="$PWD/.dagster" uv run dagster dev -m events_coverage.definitions -d src
```

`uv sync` installs the locked project environment. `.dagster/` is local runtime state and is
ignored by Git. Setting `DAGSTER_HOME` there keeps run history for this project separate from
other Dagster projects. `dagster dev` starts both the web interface and the background process
it uses locally, then prints the local address (normally `http://127.0.0.1:3000`). The
`-m` option names the definitions module; `-d src` tells Python where that module lives.

Dagster 1.13 prints a `SupersessionWarning` recommending its optional newer `dg` helper. The
core command above still works and keeps this project smaller, so `dg` is deliberately
postponed. Reconsider it only if this command stops working or the project needs a feature
specific to `dg`.

In the interface:

1. Open **Assets** and inspect the dependency graph before running it.
2. Open **Jobs**, select `static_refresh`, and review the asset selection.
3. Launch the job once. Follow the run log and watch the assets materialize in dependency
   order.
4. Return to an asset such as `raw/event_matches` to inspect its row-count metadata and its
   upstream/downstream links.

Stop the local process with `Control-C` in the terminal where `dagster dev` is running.

DuckDB permits only one writer. Close any separate connection to
`data/warehouse/events.duckdb` before launching the refresh. Metabase uses its own published
copy and does not need the working file.

## What `static_refresh` runs

The current job reuses the project commands rather than reimplementing their logic:

1. `scripts/check_inputs.py` verifies that the primary SQLite and CSV inputs can be read.
2. `scripts/load_warehouse.py` replaces the seven `raw` DuckDB tables.
3. `dbt build` loads the seeds, builds the models and runs the dbt tests.
4. `scripts/publish_warehouse_for_metabase.py` makes the pruned DuckDB copy for Metabase.

The dashboard JSON export and standalone HTML build remain available as manual working
artifacts, documented in `dashboard/README.md`. They are not Dagster assets in this phase.
The single raw loader remains one operation because it has one DuckDB writer and intentionally
refreshes the raw layer as a consistent set.

## How this grows into weekly updates

The future pipeline should be added in small upstream layers rather than making
`static_refresh` larger all at once:

1. **Acquisition assets:** save a dated posts batch and a dated FOM report without modifying
   an older batch. Record the source, retrieval time, and coverage window.
2. **Processing assets:** clean text and produce summaries and embeddings. Partition these by
   time so one new week does not repeat the full history.
3. **Matching assets:** build a versioned post-event match set with its model, prompt/query,
   thresholds, date, and input paths recorded alongside it.
4. **Incremental warehouse/dbt work:** load only new batches and make only the justified large
   models incremental.
5. **Quality gates:** add checks for freshness, expected row ranges, missing weeks, embedding
   completeness, and matching settings.
6. **Weekly schedule:** only after the upstream steps are repeatable and safe to retry, attach
   a schedule to the full weekly asset selection. A failed week should be rerunnable without
   duplicate posts or overwritten provenance.

This preserves the current trustworthy static build while replacing its inputs one boundary
at a time.

## Code map

- `src/events_coverage/definitions.py` — the single code location loaded by Dagster.
- `src/events_coverage/defs/static_pipeline.py` — assets, dbt integration, and the manual job.
- `tests/test_dagster_definitions.py` — fast graph checks; these do not rebuild data.
- `pyproject.toml` — the three required Dagster packages and pytest's direct `src/` path.

Current Dagster documentation: [Dagster overview](https://docs.dagster.io/) and
[dbt integration](https://docs.dagster.io/integrations/libraries/dbt).
