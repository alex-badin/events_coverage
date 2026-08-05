# Events Coverage

Historical media-intelligence project for comparing how different media groups covered the same key public events.

The project starts from two local data sources:

- `news_data/`: historical media messages, currently a SQLite database with about 3.86 million rows from 2018-04-16 through 2025-04-02.
- `fom_events/`: weekly FOM event reports and extracted event tables.

The intended output is a dashboard for analysts, researchers, bloggers, political observers, and media-monitoring teams. It should answer questions like:

- Which media groups covered a FOM-noticed event heavily, lightly, or not at all?
- Which groups mentioned the event early, late, or only after other groups?
- Which words, angles, and repeated frames were different by media group?
- Which stories were amplified through views and forwards?
- Which topics were common in public attention but weak in media coverage, or the reverse?

## Project Map

```text
news_data/              Local historical news-message dataset (SQLite, gitignored).
fom_events/             FOM reports, extraction scripts, and event tables.
configs/                Source groups, framing instrument, and path defaults.
docs/                   Data architecture blueprint, pipeline docs, methodology, inventory.
scripts/                Pipeline entry points and command-line checks.
scripts/remote/         Script shipped to the Neo LAN box for remote retrieval scoring.
src/events_coverage/    Reusable project code (matching, framing, faithfulness).
data/interim/           Per-message framing/narrative records (jsonl, tracked in git).
data/processed/         Event datasets + manifests (manifests tracked in git).
queries/                Reusable SQL query templates.
outputs/                Generated comparison tables, heatmaps, chart exports.
reports/                Rendered analyses; reports/generators/ holds the render scripts.
skills/                 Agent skill for evidence-backed result reports.
dashboard/              Dashboard app code or dashboard-specific notes (not started).
tests/                  Test area (empty so far).
```

## First Check

Run this before analysis work:

```sh
python3 scripts/check_inputs.py
```

It checks that the main local data files are readable, opens the SQLite database, and prints basic counts for the FOM event table. For a slower full SQLite health check, add `--full`.

## Pipelines (implemented)

**1. Build a single-event news dataset** — [docs/event_dataset_pipeline.md](docs/event_dataset_pipeline.md)

```sh
.venv/bin/python scripts/build_event_dataset.py --event "<FOM event name>" --year 2025 --week 11 --slug my_event_2025w11
```

Qwen3 embedding retrieval over the full corpus (vectors live on the Neo LAN box, scored over SSH) plus Cohere rerank. Needs `OPENROUTER_API_KEY` and `COHERE_API_KEY` in `.env`, and SSH access to Neo. Outputs `event_<slug>_{dataset,candidates,review_sample,manifest}` in `data/processed/`.

**2. Compare framing across media groups** — [docs/framing_pipeline.md](docs/framing_pipeline.md)

```sh
.venv/bin/python scripts/extract_framing.py --slug my_event_2025w11 --workers 4   # gpt-5.5, resumable
.venv/bin/python scripts/induce_narratives.py --slug my_event_2025w11
.venv/bin/python scripts/compare_framing.py --slug my_event_2025w11 --bootstrap 1000
```

Per-message structured framing records (`data/interim/`), induced narratives, and within-group comparison tables/heatmaps (`outputs/`, `reports/`). The instrument is defined in `configs/framing_schema.yaml` and documented in [docs/framing_methodology.md](docs/framing_methodology.md). Read [docs/framing_readout_caveats.md](docs/framing_readout_caveats.md) before quoting aggregate numbers.

**3. Render reports** — `reports/generators/`, indexed in [reports/README.md](reports/README.md).

## Current Data Notes

The news database is the main media source. Its main table is `unified_messages`.

Text fields differ sharply in coverage — choose deliberately:

- `summary`: filled for most rows (3,848,244), pre-flattened; used for embeddings/retrieval, not for framing.
- `original_message`: available for every row; the standard field for framing extraction.
- `raw_message` and `cleaned_message`: only on the smaller collected subset (190,426 rows).
- `views` and `forwards`: engagement-style counters where available.
- `stance`: sparse — use `configs/media_groups.yaml` for stable group comparisons (it is a draft grouping).
- `embedding` (in-DB column): archived sparse Cohere store, not used; current embeddings are the full-corpus Qwen3 sidecar on Neo (see [docs/data_inventory.md](docs/data_inventory.md), and [docs/neo_box.md](docs/neo_box.md) for how to run anything on that machine).

The cleaned FOM event table is `fom_events/processed_events/events_table.csv`: 3,687 event rows across 2020-2025.

## Setup

This project is Python-oriented. Install dependencies with:

```sh
uv sync
```

Copy `.env.example` to `.env` and fill in the API keys (the example file explains which script needs which key). If you are only checking the current data inventory, no external Python packages are needed: `python3 scripts/check_inputs.py`.

## Status (2026-08-02)

**The analytical pilot is done and the data layer around it is largely built.** The blueprint,
including the measured sizing and the staged dbt scope, is
[docs/data_architecture.md](docs/data_architecture.md). The product core is coverage metrics
computed in plain SQL; framing and narrative extraction are out of scope for this phase — the
pipeline and its outputs stay, but the instrument is not being extended.

Built so far:

- **DuckDB warehouse** — `scripts/load_warehouse.py` loads the matched post sets, the FOM event
  table, the source-to-group map, and posts-per-source-per-day across the whole corpus (the
  denominator that separates "said nothing about this" from "was not publishing").
- **dbt project** — staging, intermediate and marts layers with generic and hand-written tests, a
  stopword seed, a stemming macro, and column documentation. `cd dbt && ../.venv/bin/dbt build`.
- **Prototype dashboard** — one self-contained HTML file built from the marts; see
  [dashboard/README.md](dashboard/README.md).
- **Metabase** — Docker setup plus a script that provisions the connection, the questions and the
  dashboard through Metabase's own interface; see [metabase/README.md](metabase/README.md).

Not built: Dagster orchestration.

What the pilot produced: 16 event dataset files covering 10 distinct events, of which 5 are complete
and current with 4,108 matched messages between them; framing extracted for six events (all in the
2025 news window); and two events analyzed in depth (Kursk/Sudzha 2025-W11, Trump–Zelensky
2025-W10). The evidence-backed snapshot of what exists and what it shows is
`reports/pilot_analysis_summary.md`; rendered analyses are indexed in `reports/README.md`.

Two groups of dataset files in `data/processed/` are known-incomplete and excluded from the
warehouse. Four early attempts made before the full-corpus embeddings are marked
`_cohere_archived` and are not being rebuilt. Five more, the ones without a `_qwen3` suffix, could
only search part of each window; every one of them was rebuilt on 2026-08-03 against the Qwen3
vectors, and the rebuilds are what the warehouse loads. The framing outputs are attached to the
older builds and were not redone, because framing work is out of scope for this phase.

One of those rebuilds, «Рост цен, тарифов», kept no posts at all at the standard relevance
cut-off of 0.35 — the highest score among its 3,000 candidates was under 0.30 — so it is not
loaded. Its earlier version only had rows because it used a cut-off of 0.10.
