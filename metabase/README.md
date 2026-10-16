# Metabase on the DuckDB warehouse

The reporting layer named in [docs/data_architecture.md](../docs/data_architecture.md).
Metabase connects to the warehouse and reads the marts; the charts are built in Metabase
itself rather than in code, which is the point of using it.

## What is in this folder

| Path | What |
|---|---|
| `start.sh` | Starts Metabase in Docker with the DuckDB driver and the published warehouse. |
| `provision.py` | Creates the database connection, the saved questions and the two dashboards through Metabase's own interface, so the whole setup is reproducible instead of hand-clicked. |
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
connection, the questions and the dashboards:

```sh
METABASE_USER='you@example.com' METABASE_PASSWORD='your-password' .venv/bin/python metabase/provision.py
```

The cards read the published file live. Run the script again after a publish that adds
weeks, themes or areas: the filter lists and the week the Week dashboard opens on are taken
from the published file when the script runs. It also asks Metabase to re-read the tables.
Everything is matched by name, so a rerun updates in place instead of adding copies.

Stop it with `docker rm -f events-coverage-metabase`. Saved questions survive in `app-data/`.

## What the provisioning script builds

Two dashboards in an "Events coverage" collection, mirroring the two views of the standalone
page in `dashboard/` (see `dashboard/README.md`). Clicking moves between them with the
filters already set.

**Events coverage — Overview**, across all survey weeks. Filters: Area and Theme. With both
picked, the theme decides.

- Headline numbers: survey weeks, named events, events with measured coverage, distinct
  matched posts.
- *What people noticed, week by week*: one row per calendar week, one column per area of
  news, each cell shaded by mentions per 100 respondents. Metabase has no heatmap chart, so
  this is a table with colour bands. Weeks without a FOM list say so. Click a week to open
  it.
- *Week by week for the area or theme picked*: the scope's mentions, its top event and how
  many of its events are measured, week by week. Click a week to open it.
- *How this theme was put together*: every FOM wording in the scope, with the first and last
  week it was named. Click either week to open it on that event.
- *Coverage measured so far*: measured events by media group, as matched posts per 1,000 of
  the group's own posts. The last row adds them up with each post counted once (from
  `theme_group_coverage`). Click an event to open it.

**Events coverage — Week**, one survey week. Filters:

- **Week** takes values like `2025-W10`. Its dropdown marks the weeks with measured coverage.
- **Event** takes the FOM wording itself. Clicking an event fills it in. When it is empty,
  or names an event from another week, the page shows the week's first measured event.
- **Media group** and **Word** narrow the words and posts.

Cards:

- A header row with the dates, plus clickable previous and next survey weeks and the
  nearest weeks with measured coverage.
- *What people named this week*: the whole FOM list, with each event's theme and coverage
  status. Click an event to show it. Click a theme to see it on the Overview.
- *The event shown*: share, theme, coverage status, how its posts were matched, respondent
  quotes, and the warning when its counts cannot be compared with other events.
- Group bars, every number by group, and coverage day by day.
- The words each group used more than the others. Clicking a word picks that word and its
  group.
- The matched posts behind the numbers, most relevant first.

The honesty rules of the standalone page hold here too:

- An event without a matched post set reads **not measured yet**, never 0. On the Week
  dashboard its coverage cards are empty ("No results!"), not zeros.
- **"0 of N posts"** (published, nothing matched) and **"not publishing in this window"**
  (published nothing) are different cells.
- Totals over several events count **each post once**.
- Survey sums are **mentions per 100 respondents**, never a share of people.

Every question is native SQL over the published marts, so what a card shows can be traced to
a model in `dbt/models/marts/` and from there back to the source files.

Metabase remembers the filter values each user last used on a dashboard. So a dashboard can
open on an old Area or Week rather than its default. Clear the filter to reset it.

The script also archives what its single-page version built: the "Events coverage" dashboard
and its questions. Archived items sit in Metabase's trash and can be restored from there.

Checked on 2026-10-17 against a fresh Metabase v0.62.7. Both dashboards were built from
nothing, a second run changed nothing, and an instance holding the old single-page setup
was upgraded cleanly. Every card returned the same rows through Metabase as the same SQL
run directly in DuckDB.
