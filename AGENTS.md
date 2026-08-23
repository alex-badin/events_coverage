# Events Coverage

Compares how Russian-language media groups covered the same public-agenda events — the
weekly FOM opinion surveys, 2020–2025. A historical dashboard, not a daily monitor.

**This is a personal project, built to learn the modern data stack and to stand as a
portfolio piece.** Two things follow. Prefer a clean, tested, documented build over more
features — resisting scope growth is the point, not a constraint. And Alex is learning dbt
and Dagster here: explain what a step does and why before doing it, and hand over the short
commands to run rather than running everything.

## Current phase — coverage metrics through a local warehouse

Built: DuckDB warehouse, dbt (15 models, 90 data tests, 2 unit tests), Metabase, and a
standalone HTML dashboard. Not built: Dagster and incremental models. A dated history of
the source-to-group map is deferred — no source is known to have changed group.
Blueprint: `docs/data_architecture.md`.

Framing and narrative extraction are **out of scope for this phase**. The pipeline and its
outputs stay in the repo and stay valid; do not extend the instrument, add framing fields,
or start new framing runs.

## Commands

```sh
.venv/bin/python scripts/check_inputs.py       # are the raw inputs readable?
.venv/bin/python scripts/load_warehouse.py     # raw tables -> data/warehouse/events.duckdb
cd dbt && ../.venv/bin/dbt build               # models + tests; always run dbt from dbt/
cd dbt && ../.venv/bin/dbt docs serve          # the model graph and column docs
```

Full dashboard rebuild: `dashboard/README.md`. Metabase: `metabase/README.md`.
API keys go in `.env`; `.env.example` says which script needs which.

DuckDB allows one writer at a time — close any open connection to the warehouse file before
running dbt, or the run fails on a lock.

## Layout

- `scripts/` pipeline entry points · `src/events_coverage/` shared code
- `dbt/` the warehouse transformations · `data/warehouse/` the DuckDB file (not in git)
- `news_data/`, `fom_events/` raw inputs, read-only · `configs/` source groups and paths
- `data/interim/`, `data/processed/` derived data · `outputs/`, `reports/` results
- The full-corpus Qwen3 embeddings live on a LAN machine called Neo, not here; retrieval
  reaches them over SSH (`scripts/remote/neo_qwen_retrieve.py`, `docs/neo_box.md`).

Keep raw inputs unchanged. Write derived data under `data/`, results under `outputs/` or
`reports/`. When a step uses model-generated labels, record the prompt, model name, date and
paths alongside the output.

## Traps

- **Cyrillic keyword matching.** SQLite `lower()` and `LIKE` are ASCII-only and silently miss
  capitalised Cyrillic («Курск»). Keyword checks run in Python
  (`src/events_coverage/matching.py`), never in SQL. And a keyword hit is not proven
  coverage — check examples.
- **Event datasets: use only the `_qwen3` ones.** Every event was rebuilt that way on
  2026-08-03; the versions without the suffix could search only part of each window and
  under-count. `_cohere_archived` ones are incomplete for the same kind of reason.
  `scripts/load_warehouse.py` holds the list actually loaded — trust it over the folder.
- **`event_prices_2025w11*` has no usable matched set.** At the standard relevance cut-off of
  0.35 it keeps 0 posts; its highest rerank score is under 0.30. The old build only had rows
  because it used 0.10. Do not quote those 50 posts as coverage.
- **The news snapshot ends 2025-04-02.** Never describe results as current after that date.
- **Text columns differ sharply in coverage and in what they preserve.** `summary` is
  pre-flattened — retrieval only, never tone. `original_message` is the text field, and war
  and military channels store it as a Telegram JSON blob. Details in
  `docs/data_inventory.md`.
- **`configs/media_groups.yaml` is a working analytical grouping, not a final political
  label set.** All 84 sources are resolved: 56 in scope across six groups, 28 archived and
  filtered out everywhere including the coverage denominators.
- **Narrative labels from `induce_narratives.py` are a per-run lens** — induction is
  stochastic. The per-message framing fields are the stable part.
- This project compares coverage. It does not judge whether the covered events are true.

## Docs

`docs/data_architecture.md` the plan · `docs/methodology.md` metric definitions ·
`docs/data_inventory.md` what is in the data · `docs/event_dataset_pipeline.md` how matching
works · `reports/README.md` the rendered analyses · `skills/events-coverage-analytics-report/`
the standard for reporting results (metric, base counts, denominator, visible table).
