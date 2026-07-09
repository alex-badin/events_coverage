# Project Instructions

This project analyzes how different media groups covered the same public events over a long historical period. The goal is not a daily news monitor. The goal is a structured historical dashboard that shows what each media group paid attention to, ignored, repeated, amplified, or framed differently.

## Communication Style

When explaining work, analysis, or results:

- use simple everyday words
- be a bit more detailed than the default
- explain what you did, what you found, and what you plan to do next when relevant
- prefer clear direct sentences over shorthand, jargon, or internal process language
- avoid tool names, abbreviations, and internal terms unless they truly help; if one is needed, explain it right away
- do not assume the user has the same context you built up while working
- when mentioning a file, command, or technical concept, add a short plain-language explanation if needed
- prefer short paragraphs; use lists only when they make the reply easier to scan

## Working Style

- Before doing downstream work, verify that any primary input file is readable. If a required file is missing, unreadable, or permission-blocked, stop and report the blocker; continue only if the user requested a fallback or the workflow explicitly supports one.
- Keep raw input data unchanged unless the user explicitly asks to rewrite or move it.
- Write cleaned or derived data to `data/interim/` or `data/processed/`.
- Write charts, dashboard exports, cached joins, and report outputs to `outputs/` or `reports/`.
- Prefer small, reproducible scripts over one-off notebook-only work when a step will be reused.
- If a step uses model-generated labels, keep the prompt, model name, date, and input/output path in the output notes.

## Current State (last updated 2026-07-09)

Two pipelines are implemented and were piloted on real events. Read their docs before touching them — they record verified findings and traps, not just usage:

1. **Event dataset (matching):** `scripts/build_event_dataset.py` finds the news messages covering one FOM event — Qwen3 embedding retrieval plus Cohere rerank. Doc: `docs/event_dataset_pipeline.md` (includes the dataset naming rules for `data/processed/`).
2. **Framing comparison:** `scripts/extract_framing.py` → `scripts/induce_narratives.py` → `scripts/compare_framing.py` compares how media groups frame one matched event. Operational doc: `docs/framing_pipeline.md`; instrument reference: `docs/framing_methodology.md`; and read `docs/framing_readout_caveats.md` before quoting aggregate numbers.

Rendered analyses and the scripts that build them live in `reports/` — the index is `reports/README.md`. The current factual status snapshot of the pilot is `reports/pilot_analysis_summary.md`.

API keys go in `.env`; `.env.example` explains which script needs which key. The full-corpus Qwen3 embeddings (3,848,244 summaries) live in a sidecar on a separate LAN machine called Neo, not in this repo; retrieval reaches them over SSH via `scripts/remote/neo_qwen_retrieve.py`.

There is a project skill for writing result reports: `skills/events-coverage-analytics-report/SKILL.md` (claim standards: every comparison needs the metric, base counts, denominator, and a visible table or chart).

## Current Primary Inputs

- `news_data/ask_media_unified_messages_20260604.db`: main historical media-message database. The main table is `unified_messages`.
- `news_data/ask_media_unified_messages_20260604_README.md`: notes about the news database build and columns.
- `news_data/ask_media_unified_basic_stats_20260604.md`: verified summary of news coverage volume, dates, and source counts.
- `fom_events/processed_events/events_table.csv`: default cleaned FOM weekly event table for analysis.
- `fom_events/downloaded_reports/`: source PDF reports used to create the FOM event table.

`fom_events/events_table.csv` is a working file and includes blank event names. Do not use it as the default analysis input unless the task is about debugging the FOM extraction process.

## Text Fields — Choose Deliberately

The database has several text columns with very different coverage. Do not confuse them:

- `summary`: filled for 3,848,244 of 3,861,614 rows, but it is a pre-flattened summary — tone and framing are already lost. Used for embeddings and retrieval, never for framing extraction.
- `original_message`: filled for every row. This is the standard field for framing work. War/military sources store it as a Telegram JSON blob (`{"_":"Message",…}`); `framing.normalize_text` unwraps it.
- `raw_message` / `cleaned_message`: only on the smaller collected subset (190,426 rows).
- `stance`: sparse (collected subset only) — use `configs/media_groups.yaml` for stable group comparisons.
- `embedding` (in-DB column): archived sparse Cohere store (~4.9% of rows, mostly Feb–Apr 2025). Do not build on it; the current embeddings are the Qwen3 sidecar on Neo. See `docs/data_inventory.md`.

## Cautions

- Do not treat keyword matches as proven coverage without checking examples. Also: SQLite `lower()`/`LIKE` are ASCII-only and silently miss capitalized Cyrillic («Курск»), so keyword checks are done in Python (`src/events_coverage/matching.py`), not in SQL.
- Do not treat source groups as final political labels; `configs/media_groups.yaml` is a draft grouping with ~31 uncategorized sources.
- The news data ends on 2025-04-02 in the current local snapshot. Do not describe results as current after that date.
- Narrative labels from `induce_narratives.py` are a per-run lens (induction is stochastic); the per-message framing fields (roles, epistemic status, action labels) are the stable substrate.
- Datasets in `data/processed/` whose names contain `_cohere_archived` were built on the archived sparse Cohere embeddings and are known-incomplete. Do not use them for conclusions; rebuild with the qwen3 retriever first.
- The project is for comparative media intelligence, not for judging factual truth of the covered events.
