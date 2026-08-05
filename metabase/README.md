# Metabase on the DuckDB warehouse

The reporting layer named in [docs/data_architecture.md](../docs/data_architecture.md).
Metabase connects to the warehouse and reads the marts; the charts are built in Metabase
itself rather than in code, which is the point of using it.

## What is in this folder

| Path | What |
|---|---|
| `start.sh` | Starts Metabase in Docker with the DuckDB driver and the published warehouse. |
| `provision.py` | Creates the database connection, the saved questions and the dashboard through Metabase's own interface, so the whole setup is reproducible instead of hand-clicked. |
| `plugins/` | The DuckDB driver jar. Not in git — download it, see below. |
| `data/` | The copy of the warehouse Metabase reads. Not in git — produced by `scripts/publish_warehouse_for_metabase.py`. |
| `app-data/` | Metabase's own storage for saved questions and dashboards. Not in git. |

## Why Metabase reads a copy of the warehouse

DuckDB allows one writer at a time, and `dbt build` rewrites the warehouse file on every
run. If Metabase held the working file open, a dbt run would either fail or leave Metabase
pointing at a file that had been replaced underneath it.

So there is a publish step: transformations write `data/warehouse/events.duckdb`, then
`scripts/publish_warehouse_for_metabase.py` hands a finished snapshot to
`metabase/data/events.duckdb`. That script also drops everything except the marts — staging
and intermediate models are working steps, not answers, and putting them in front of a
dashboard builder invites charts built on half-finished numbers. The folder is mounted
read-only, so the reporting tool cannot write to its own source.

## The DuckDB driver

Metabase has no built-in DuckDB support. The driver is a separate plugin, maintained by
MotherDuck: <https://github.com/motherduckdb/metabase_duckdb_driver>

Version matters and is easy to get wrong. The driver bundles its own copy of DuckDB, and a
driver built against an older DuckDB cannot open a file written by a newer one. The warehouse
here is written by the DuckDB Python library, so the two have to be kept in step.

| | Version |
|---|---|
| Driver release | 1.5.4.0, bundling DuckDB 1.5.4, built for Metabase 62 |
| Metabase | v0.62.7, downloaded by `Dockerfile` from metabase.com |
| DuckDB writing the warehouse | 1.5.5 (the Python library in `.venv`) |

Checked on 2026-08-02: the driver registers (`Registered driver :duckdb` in the container
log) and reads the warehouse written by DuckDB 1.5.5 — a query through the driver returned
the same numbers as the prototype dashboard.

**The official `metabase/metabase` image will not work.** It is built on Alpine Linux, which
uses musl rather than glibc, and the driver ships a compiled DuckDB library built for glibc.
Tried here: on the official image the library failed to load, and after adding `libstdc++`
and the `gcompat` shim it loaded and then killed the Java process from inside the native
library. The driver's own documentation says the same and recommends a Debian base, which is
what `Dockerfile` uses.

The jar is not in git. Download it into `plugins/` before the first build:

```sh
curl -L -o metabase/plugins/duckdb.metabase-driver.jar https://github.com/motherduckdb/metabase_duckdb_driver/releases/download/1.5.4.0/duckdb.metabase-driver.jar
```

If a future `uv sync` moves the Python DuckDB library to a version the driver cannot read,
the symptom is Metabase failing to connect with a storage-version error. The fix is to take a
newer driver release, or to write the published copy in an older storage format.

## Running it

From the repository root, after `dbt build`:

```sh
.venv/bin/python scripts/publish_warehouse_for_metabase.py
```

```sh
zsh metabase/start.sh
```

The first `start.sh` builds the image, which takes a few minutes; after that it starts in
seconds. Then open <http://localhost:3000>. The first run asks you to create an admin
account — pick your own email and password; nothing in this repository sets or stores them,
and `provision.py` refuses to run until that account exists.

With the account created, point the provisioning script at it and it will build the
connection, the questions and the dashboard:

```sh
METABASE_USER='you@example.com' METABASE_PASSWORD='your-password' .venv/bin/python metabase/provision.py
```

Stop it with `docker rm -f events-coverage-metabase`. Saved questions survive in `app-data/`.

## What the provisioning script builds

One dashboard, "Events coverage", with the same questions the prototype answers:

- the event list with survey share against matched posts
- which events landed with which kinds of media, and with their audiences
- coverage by media group for a chosen event, in raw posts and per thousand of the group's
  own output
- who published first, and how long after the search window opened
- coverage day by day
- the words and phrases that separate the groups
- the matched posts themselves

Each question is native SQL against one mart, so what a chart shows can be traced to a model
in `dbt/models/marts/` and from there back to the source files.
