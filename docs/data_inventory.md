# Data Inventory

This document records what was found during project initialization.

## News Data

Primary file:

```text
news_data/ask_media_unified_messages_20260604.db
```

Main table:

```text
unified_messages
```

Verified high-level stats from the local summary files:

- Rows: 3,861,614
- Distinct sources: 84
- Date range: 2018-04-16 through 2025-04-02
- Rows with summaries: 3,848,244
- Rows with raw collected message text: 190,426
- Rows with embeddings: 179,988

Useful fields in `unified_messages`:

- `source`
- `message_id`
- `original_message`
- `summary`
- `date`
- `views`
- `forwards`
- `embedding`
- `stance`
- `source_dbs`

Important caution: `stance` is not filled for every row. Use it carefully. For stable dashboard grouping, prefer `configs/media_groups.yaml` and keep the grouping reviewable.

## FOM Event Data

Default analysis file:

```text
fom_events/processed_events/events_table.csv
```

Observed shape:

- Rows: 3,687
- Years covered: 2020-2025
- Blank event names: 0
- Missing percentages: 4

Columns:

- `date`
- `year`
- `week`
- `event`
- `description`
- `percentage`

Working/raw extraction file:

```text
fom_events/events_table.csv
```

This file contains blank event names, so use it mainly for extraction debugging.

## Existing FOM Work Files

The `fom_events/` folder also contains:

- extraction prompts
- PDF-processing scripts
- downloaded FOM reports
- older extraction outputs
- a notebook for event analysis

Some scripts still point to an older absolute path from another project. Update paths before reusing them here.
