# Events Coverage

Compares how Russian-language media groups covered the same public-agenda events — the
weekly FOM opinion surveys, 2020–2026. A historical dashboard, not a daily monitor.

**This is a personal project, built to learn the modern data stack and to stand as a
portfolio piece.** Two things follow. Prefer a clean, tested, documented build over more
features — resisting scope growth is the point, not a constraint. And Alex is learning dbt
and Dagster here: explain what a step does and why before doing it, and hand over the short
commands to run rather than running everything.

Before adding any dependency, build system, framework, or configuration, first explain what
it is, why the current task needs it, what the simpler alternative is, and whether it can be
postponed. Do not add it before giving that explanation.

## Current phase — coverage metrics through a local warehouse

Built: DuckDB warehouse, dbt (models, data tests, unit tests), Metabase, a standalone HTML
dashboard (an overview across all survey weeks and a per-week view), cross-week themes for every
FOM event (`dbt/seeds/README.md`), and the first manual Dagster graph from static inputs through
dbt to the Metabase snapshot. Not built: automated ingestion, a weekly schedule, or incremental models.
A dated history of the source-to-group map is deferred — no source is known to have changed group.
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

`.claude/hooks/ask-before-paid-run.sh` asks the user before a Python command that reaches a paid
service (a script whose file names a vendor or paid helper, or inline code that fetches a key or
calls a billed endpoint). Once one paid run is approved, no paid run in this project is stopped
for 12 hours, in any session. Spending rule: one yes to a task with its stated cost or budget
covers every paid run of that task, side sessions included. Ask again only to go over that
budget or for a different task; when briefing a side session, pass the budget as already agreed.
Before proposing a paid run, say which decision it changes and try the free or cheaper way first
(data already on disk, a smaller sample, fewer tokens per call). Estimate from typical items, not
from the largest test cases, and propose the smallest run that answers the open question; a
budget for a whole task comes only after its cost per item is measured.

DuckDB allows one writer at a time — close any open connection to the warehouse file before
running dbt, or the run fails on a lock.

`prepare_if_dev()` refreshes `dbt/target/manifest.json` only under `dagster dev`. After
editing dbt files, run `dbt parse` before `uv run pytest` or `dagster job execute`, or they
read the old manifest.

The owner's Claude Project (cloud threads) sees only what is pushed to GitHub: when a local session leaves
tracked changes uncommitted or unpushed, say so at the end, or the Project keeps working from a stale copy.

## Layout

- `scripts/` pipeline entry points · `src/events_coverage/` shared code
- `dbt/` the warehouse transformations · `data/warehouse/` the DuckDB file (not in git)
- `news_data/`, `fom_events/` raw inputs, read-only · `configs/` source groups and paths
- `data/interim/`, `data/processed/` derived data · `outputs/`, `reports/` results
- The full-corpus Qwen3 embeddings live on a LAN machine called Neo, not here; retrieval
  reaches them over SSH (`scripts/remote/neo_qwen_retrieve.py`, `docs/neo_box.md`). So do the full-text
  vectors of the new posts (`new_weeks_2026-11-03`), which only a re-run of candidates needs.

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
- **Three matching methods are loaded; never compare them.** The 5 events before 2025-W12 are summary +
  Cohere at 0.35 (`scripts/build_event_dataset.py`, do not build new sets on it). 2025-W12..2026-W20 (644
  events) are full text + OpenAI Decisions API with a per-event cut-off
  (`exploration/2026-11-03_new_weeks/`). 2026-W21..W43 (226 events) are the same candidates + a Luna 0-100
  score through Codex (`exploration/2026-11-06_luna_direct/`). The 2020–2025 history has not been re-run; the
  decision is that every specific FOM event ends up on one method.
- **Do not rerun `new_weeks.py export`:** it rewrites `configs/new_weeks_events.json` and drops W21–W43. After it,
  `luna_finish.py export` adds them back.
- **Luna through Codex gives no probabilities and its yes/no labels are unstable on broad events** (F1 0.727, then
  0.638 on the same input); ask for a 0-100 score and set the cut-off from a sample. Use `--ignore-user-config`:
  otherwise every `codex exec` on the main account starts all its MCP servers and tens of parallel calls overload
  the Mac (load average 971).
- **`dbt build` needs more memory for `event_group_terms` now:** `DUCKDB_MEMORY_LIMIT=10GB`; the default 6 GB runs
  out.
- **OpenAI billed $13.62 of Decisions attempts that never returned a response**, nearly all while the run sat at
  the 10M tokens-per-minute limit, with the SDK set to retry. A ledger built from responses under-counts:
  use `max_retries=0`, stay below the limit, and compare with the Usage API (`OPENAI_API_ADMIN_KEY` in
  `.env`; `OPENAI_ADMIN_KEY` there is another organisation's).
- **`event_prices_2025w11*` has no usable matched set.** At the standard relevance cut-off of
  0.35 it keeps 0 posts; its highest rerank score is under 0.30. The old build only had rows
  because it used 0.10. Do not quote those 50 posts as coverage.
- **Posts come from two files.** The archive (`news_data/ask_media_unified_*.db`) ends 2025-04-02; never
  describe results as current after that date unless they use the second file,
  `news_data/telegram_previews_2026-11-03.sqlite` (`scripts/collect_telegram.py`, public t.me/s pages): no
  forward counts, views as text («1.2K»), line breaks flattened, so `posts.text` is not byte-equal to the
  archive's `original_message`. They join on (source, message_id); the boundary posts are in both files.
- **Never add matched posts across events.** Search windows of neighbouring weeks overlap, so one
  post can be matched to two events (130 are). Totals over several events come from
  `theme_group_coverage`, which counts each post once over the union of window days.
- **Text columns differ sharply in coverage and in what they preserve.** `summary` is
  pre-flattened — retrieval only, never tone. `original_message` is the text field, and war
  and military channels store it as a Telegram JSON blob. Details in
  `docs/data_inventory.md`.
- **`configs/media_groups.yaml` is a working analytical grouping, not a final political
  label set.** All 84 sources are resolved: 56 in scope across six groups, 28 archived and
  filtered out everywhere including the coverage denominators.
- **Narrative labels from `induce_narratives.py` are a per-run lens** — induction is
  stochastic. The per-message framing fields are the stable part.
- **OpenRouter refuses every `openai/*` model for this key** (403 "violation of provider Terms Of
  Service", even on a trivial prompt). Use OpenAI models through Codex instead. And a parallel
  `pool.map` over paid calls must save each answer as it arrives, or one bad reply loses spend
  that was already billed.
- This project compares coverage. It does not judge whether the covered events are true.

## Docs

`docs/data_architecture.md` the plan · `docs/methodology.md` metric definitions ·
`docs/data_inventory.md` what is in the data · `docs/event_dataset_pipeline.md` how matching
works · `reports/README.md` the rendered analyses · `skills/events-coverage-analytics-report/`
the standard for reporting results (metric, base counts, denominator, visible table).
