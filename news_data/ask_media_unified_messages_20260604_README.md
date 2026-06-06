# Ask Media Unified Messages Dataset

Built on: 2026-06-04

Main file:

`ask_media_unified_messages_20260604.db`

## What It Contains

This SQLite database compiles the data from:

- `summarized_messages_msi.db`
- `summarized_messages_mac.db`
- `work_data/summarized_messages_old.db`
- `work_data/collected_messages_msi.db`
- `work_data/collected_messages1.db`
- `work_data/collected_messages2.db`

The main table is `unified_messages`.

It has one row per normalized message key:

- `source`: lower-case channel/source name
- `message_id`: message id; for raw collected data, ids like `rbc_news_115174` were normalized to `115174`

The table keeps final summary fields, adds raw collected fields where available, and includes work-data-only messages that were missing from the final summary databases.

## Row Counts

- `unified_messages`: 3,861,614 rows
- rows from `summarized_messages_msi.db`: 2,342,669
- rows from `summarized_messages_mac.db`: 1,490,065
- rows from `work_data/summarized_messages_old.db`: 2,342,669
- rows with any collected/raw source data: 190,426
- rows only found in collected `work_data`: 28,880
- `channel_metadata`: 49 rows

Date range:

- earliest: `2018-04-16 09:34:40+00:00`
- latest: `2025-04-02T19:16:14+00:00`

Content coverage:

- rows with summary: 3,848,244
- rows with raw collected message text: 190,426
- rows with embedding: 179,988

## Useful Tables

`unified_messages`

The main compiled message-level dataset.

`channel_metadata`

Channel metadata copied from `work_data/collected_messages1.db`.

`dataset_metadata`

Build notes, input paths, and row-count metadata.

## Useful Columns

`source_dbs`

Comma-separated list of source databases that contributed to a row.

`present_in_summarized_msi`, `present_in_summarized_mac`, `present_in_summarized_old`

Flags showing which summary databases contained the row.

`present_in_collected_msi`, `present_in_collected1`, `present_in_collected2`

Flags showing which raw collected databases contained the row.

`raw_message`, `cleaned_message`

Raw collected text fields, when available.

`original_message`, `summary`, `is_digest`, `date`, `views`, `forwards`

Summary-level fields from the final summary databases where available.

`embedding`

Embedding value from the final Mac summary database or from collected-message databases when the final row did not already have one.

## Quick Checks

Open the dataset:

```sh
sqlite3 /Users/alexbadin/Documents/Codex/2026-06-04/users-alexbadin-github-projects-ask-media/outputs/ask_media_unified_messages_20260604.db
```

Count rows:

```sql
select count(*) from unified_messages;
```

Find work-data-only rows:

```sql
select source, message_id, date, summary
from unified_messages
where present_in_summarized_msi = 0
  and present_in_summarized_mac = 0
  and present_in_summarized_old = 0
  and (
    present_in_collected_msi = 1
    or present_in_collected1 = 1
    or present_in_collected2 = 1
  )
limit 20;
```

Inspect source coverage:

```sql
select key, value
from dataset_metadata
where key like 'rows_%'
   or key like 'unified_%'
   or key like 'channel_%'
order by key;
```

## Verification

SQLite `quick_check` returned:

```text
ok
```
