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

Posts after that are in a second file, `news_data/telegram_previews_2026-11-03.sqlite`, collected
2026-11-03 by `scripts/collect_telegram.py` from public channel previews (t.me/s/<channel>), for the
56 in-scope channels, each from its newest archived post: 1,211,509 posts (1,205,058 with text),
2025-04-02 to 2026-11-03, 53 channels with posts; `lifenews` and `riafan` have none after the
archive, `prigozhin_hat` has no public preview. Table `posts` (source_id, message_id, published_utc,
text, record_type, views_text); `pages` keeps each fetched page's HTML. No forward counts; views are
display text; line breaks are flattened. The 51 boundary posts present in both files have the same
id, time and text (up to whitespace).
- Rows with summaries: 3,848,244
- Rows with the post's own text in `original_message`: 99.3–100% of every month from 2020-01 to
  2025-04 (counted in the DB on 2026-10-18; the 190,426 given here before was wrong). Before
  2025-02 it is plain text; from 2025-02 war and military channels store a Telegram JSON blob
  (23% of March 2025 posts), which is why average length jumps from about 500 to over 1,000 chars.
- Rows with an in-DB `embedding` value (Cohere JSON): 179,988 — this is the *old, sparse*
  embedding column. The full corpus is now separately embedded with Qwen3; see "Embeddings" below.

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

## Embeddings

We work with **one** embedding store: the Qwen3 full-corpus sidecar. A second, older Cohere store
exists but is **archived** — kept only for provenance, not used by the current pipeline.

1. **Qwen3 full-corpus sidecar (current, the one we use).** The whole `summary` corpus was re-embedded
   from scratch with `qwen/qwen3-embedding-8b` (via OpenRouter, provider DeepInfra) on 2026-06-30.
   This is the default first-stage retriever in
   [`scripts/build_event_dataset.py`](../scripts/build_event_dataset.py) (`--retriever qwen3`).
   - **Rows:** 3,848,244 (every summary row — full history, not just 2025).
   - **Vectors:** native 4096-d, float16, L2-normalized.
   - **Format:** a float16 **sidecar**, not stored in the DB — `vectors.f16` (29.36 GB) +
     `index.tsv` + `manifest.json`.
   - **Location:** on the **Neo** LAN box (`ssh $NEO_HOST`, set in `.env`) at
     `C:\emb_test\ec\data\processed\qwen3emb_8b\`. It stays there by design; scoring runs on Neo
     over SSH via [`scripts/remote/neo_qwen_retrieve.py`](../scripts/remote/neo_qwen_retrieve.py)
     (only the small query matrix out and per-doc scores back cross the network — never the 29 GB
     file). Built by
     [`scripts/backfill_embeddings_openrouter.py`](../scripts/backfill_embeddings_openrouter.py).
   - **Cost of the build:** ~$3.36 (336.4M input tokens).

2. **In-DB Cohere `embedding` column (ARCHIVED — do not use).** `embed-multilingual-v3.0`, 1024-d,
   `input_type=clustering`, on the `summary` field, stored as JSON text in `unified_messages.embedding`.
   Present on only **179,988 rows** (~4.9% globally; ~89–100% for Feb–Apr 2025, near-zero elsewhere).
   Its sparse pre-2025 coverage was the reason for the Qwen3 from-scratch re-embed. The raw column is
   left in the DB for provenance but is **not** part of the current pipeline — do not build on it.
   (Note: Cohere `rerank-v3.5` is a *reranker*, not an embedding, and is still used in the second
   stage regardless of retriever — that is separate from these archived Cohere embeddings.)

See [`docs/event_dataset_pipeline.md`](event_dataset_pipeline.md) for how the retriever is used.

## FOM Event Data

Default analysis file:

```text
fom_events/processed_events/events_table.csv
```

Observed shape:

- Rows: 4,876 (3,699 to 2025-W11; 1,177 added 2026-11-03 for 2025-W12 to 2026-W43, extracted with
  Codex — `fom_events/codex_extraction/README.md`)
- Years covered: 2020-2026 (to 2026-W43)
- Blank event names: 0
- Missing percentages: 4
- Matched posts: 5 events before 2025-W12 (summary + Cohere) and 644 of 2025-W12..2026-W20 (full text +
  Decisions API; 632 with posts, 12 with none), which do not compare with each other. The 870 specific events
  of 2025-W12..2026-W43 also include 226 with no posts loaded, all after 2026-W20: 213 never scored (the
  end of the work queue, run stopped) and 13 scored but held back, since one event is not a week's picture.
  `exploration/2026-11-03_new_weeks/README.md` has the details and the spend reconciliation.

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
