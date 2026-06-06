# Ask Media Unified Dataset: Basic Stats

Generated on: 2026-06-04

Main database:

`ask_media_unified_messages_20260604.db`

## Headline Counts

- Rows in `unified_messages`: 3,861,614
- Distinct sources: 84
- Month buckets: 66
- Date range: 2018-04-16 through 2025-04-02
- Rows with summaries: 3,848,244
- Rows with raw collected message text: 190,426
- Rows with embeddings: 179,988
- Rows only found in collected `work_data`: 28,880

## Year Split

| Year | Rows | Sources | Rows with summary | Rows with raw message | Work-data-only rows |
|---|---:|---:|---:|---:|---:|
| 2018 | 2 | 2 | 1 | 0 | 0 |
| 2019 | 29 | 29 | 28 | 0 | 0 |
| 2020 | 403,244 | 61 | 391,725 | 0 | 0 |
| 2021 | 551,560 | 67 | 550,682 | 187 | 0 |
| 2022 | 991,280 | 80 | 991,064 | 18,670 | 82 |
| 2023 | 881,691 | 81 | 881,228 | 13,101 | 93 |
| 2024 | 837,723 | 82 | 837,488 | 28,366 | 2,123 |
| 2025 | 196,085 | 78 | 196,028 | 130,102 | 26,582 |

## Recent Month Split

| Month | Rows | Sources | Rows with summary | Rows with raw message | Rows only in collected work_data |
|---|---:|---:|---:|---:|---:|
| 2024-02 | 64,492 | 78 | 64,460 | 915 | 15 |
| 2024-03 | 82,926 | 80 | 82,906 | 1,080 | 29 |
| 2024-04 | 72,282 | 79 | 72,269 | 948 | 15 |
| 2024-05 | 74,482 | 78 | 74,468 | 1,474 | 23 |
| 2024-06 | 69,700 | 78 | 69,687 | 3,263 | 103 |
| 2024-07 | 66,792 | 77 | 66,789 | 3,099 | 60 |
| 2024-08 | 71,579 | 80 | 71,561 | 3,656 | 193 |
| 2024-09 | 68,997 | 79 | 68,972 | 3,537 | 340 |
| 2024-10 | 69,164 | 77 | 69,142 | 3,286 | 379 |
| 2024-11 | 65,107 | 78 | 65,082 | 3,075 | 456 |
| 2024-12 | 69,350 | 79 | 69,329 | 3,189 | 473 |
| 2025-01 | 56,871 | 77 | 56,852 | 2,606 | 384 |
| 2025-02 | 63,470 | 77 | 63,456 | 56,456 | 5,567 |
| 2025-03 | 71,714 | 76 | 71,690 | 67,010 | 16,601 |
| 2025-04 | 4,030 | 45 | 4,030 | 4,030 | 4,030 |

Full monthly table:

`ask_media_unified_monthly_stats_20260604.csv`

## Top Sources

| Source | Rows | First date | Last date | Work-data-only rows |
|---|---:|---|---|---:|
| tass_agency | 280,031 | 2020-06-18 | 2025-04-02 | 1,517 |
| rian_ru | 245,903 | 2020-01-01 | 2025-04-02 | 825 |
| solovievlive | 234,592 | 2020-01-01 | 2025-04-02 | 1,158 |
| rt_russian | 184,360 | 2020-01-01 | 2025-04-02 | 756 |
| izvestia | 141,347 | 2020-07-16 | 2025-04-02 | 719 |
| vestiru24 | 132,662 | 2018-04-16 | 2025-04-02 | 1,783 |
| rentv_news | 132,032 | 2020-07-20 | 2025-04-02 | 1,876 |
| zvezdanews | 124,889 | 2019-12-31 | 2025-04-02 | 557 |
| truekpru | 120,313 | 2019-12-31 | 2025-04-02 | 652 |
| aifonline | 109,107 | 2020-01-01 | 2025-04-02 | 743 |
| rgrunews | 102,916 | 2020-01-01 | 2025-04-02 | 470 |
| rbc_news | 96,952 | 2019-12-31 | 2025-04-02 | 594 |
| lentadnya | 89,415 | 2020-01-01 | 2025-04-02 | 290 |
| uranews | 88,618 | 2019-12-31 | 2025-04-02 | 845 |
| meduzalive | 87,153 | 2019-12-31 | 2025-04-02 | 788 |
| riafan | 83,455 | 2019-12-31 | 2023-06-29 | 0 |
| readovkanews | 79,401 | 2019-12-31 | 2025-04-02 | 264 |
| tsargradtv | 79,163 | 2020-01-02 | 2025-04-02 | 371 |
| ntvnews | 76,467 | 2020-01-01 | 2025-04-02 | 289 |
| mk_ru | 71,977 | 2019-12-31 | 2025-04-02 | 1,302 |

Full source table:

`ask_media_unified_source_stats_20260604.csv`

## Column Completeness

| Column | Filled rows | Missing rows | Filled % |
|---|---:|---:|---:|
| source | 3,861,614 | 0 | 100.00 |
| message_id | 3,861,614 | 0 | 100.00 |
| source_names | 3,861,614 | 0 | 100.00 |
| collected_ids | 190,426 | 3,671,188 | 4.93 |
| original_message | 3,861,614 | 0 | 100.00 |
| raw_message | 190,426 | 3,671,188 | 4.93 |
| cleaned_message | 190,426 | 3,671,188 | 4.93 |
| summary | 3,848,244 | 13,370 | 99.65 |
| is_digest | 3,861,098 | 516 | 99.99 |
| processed_at | 3,832,734 | 28,880 | 99.25 |
| date | 3,861,614 | 0 | 100.00 |
| views | 3,861,406 | 208 | 99.99 |
| forwards | 3,832,519 | 29,095 | 99.25 |
| embedding | 179,988 | 3,681,626 | 4.66 |
| embedding_processed_at | 0 | 3,861,614 | 0.00 |
| stance | 190,426 | 3,671,188 | 4.93 |
| created_at | 31,760 | 3,829,854 | 0.82 |
| source_dbs | 3,861,614 | 0 | 100.00 |

Full column table:

`ask_media_unified_column_profile_20260604.csv`

## `is_digest` and `stance`

`is_digest`:

- `0`: 3,780,216 rows
- `1`: 80,882 rows
- missing: 516 rows

`stance` appears only on collected/raw rows:

- `inet propaganda`: 65,523
- `voenkor`: 46,722
- `tv`: 30,663
- `moder`: 27,982
- `altern`: 19,536

## Original File Removal Note

The unified database contains every normalized message key found in the source folder, including the 28,880 messages found only in collected `work_data`.

However, the original collected databases still contain some alternate duplicate versions that the one-row-per-message unified table does not fully preserve:

- 101,328 raw message keys appeared in more than one collected database.
- 6,200 duplicate keys had different `raw_message` values.
- 4,241 duplicate keys had different `summary` values.
- 6,155 duplicate keys had different `views` values.
- 5,544 duplicate keys had different `embedding` values.

So the original files are no longer needed for normal analysis on one canonical row per message, but they still have audit value if exact per-source duplicate versions matter.
