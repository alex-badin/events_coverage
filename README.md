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
news_data/              Local historical news-message dataset.
fom_events/             FOM reports, extraction scripts, and event tables.
configs/                Project settings, source groups, and path notes.
docs/                   Method notes, data inventory, and planning docs.
scripts/                Reusable command-line checks and analysis helpers.
src/events_coverage/    Python package area for reusable project code.
data/interim/           Temporary cleaned joins and intermediate tables.
data/processed/         Stable derived tables ready for dashboard use.
dashboard/              Dashboard app code or dashboard-specific notes.
queries/                Reusable SQL query templates.
outputs/                Local generated charts, caches, and exports.
reports/                Written analysis outputs.
```

## First Check

Run this before analysis work:

```sh
python3 scripts/check_inputs.py
```

It checks that the main local data files are readable, opens the SQLite database, and prints basic counts for the FOM event table.

For a slower full SQLite health check, run:

```sh
python3 scripts/check_inputs.py --full
```

## Suggested Workflow

1. Start from `fom_events/processed_events/events_table.csv`.
2. Normalize event names, week dates, FOM percentage, and quote examples into a stable table in `data/processed/`.
3. Match event windows against `news_data/ask_media_unified_messages_20260604.db`.
4. Store candidate matches in `data/interim/`, with enough fields to manually audit samples.
5. Compute coverage metrics by source and source group.
6. Build dashboard tables and charts from `data/processed/`.

## Current Data Notes

The news database is the main media source. Its main table is `unified_messages`.

Useful columns include:

- `source`: media source or channel name.
- `message_id`: source-level message id.
- `date`: message date.
- `summary`: normalized message summary, filled for most rows.
- `original_message`: available for every row in the current database.
- `raw_message` and `cleaned_message`: available only for the smaller collected/raw subset.
- `views` and `forwards`: engagement-style counters where available.
- `stance`: available only on the collected/raw subset, so use `configs/media_groups.yaml` for stable group comparisons.

The cleaned FOM event table is `fom_events/processed_events/events_table.csv`. It currently has 3,687 event rows across 2020-2025.

## Setup

This project is Python-oriented. If you use `uv`, install dependencies with:

```sh
uv sync
```

If you are only checking the current data inventory, no external Python packages are needed:

```sh
python3 scripts/check_inputs.py
```

## Next Useful Build Step

The next concrete step is to create a normalized event table with one row per FOM event and explicit week start/end dates. After that, build a first matching pass for a small sample of events and inspect whether the matches are useful enough for dashboard metrics.
