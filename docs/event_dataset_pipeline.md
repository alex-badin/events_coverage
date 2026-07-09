# Single-event news dataset pipeline

Builds a high-precision set of news messages covering **one** FOM "memorable event", as the
input for comparing coverage across media groups. Implemented in
[`scripts/build_event_dataset.py`](../scripts/build_event_dataset.py) with helpers in
[`src/events_coverage/matching.py`](../src/events_coverage/matching.py).

## Inputs
- FOM events: `fom_events/processed_events/events_table.csv` (event name + quote examples + FOM %).
- News DB: `news_data/ask_media_unified_messages_20260604.db`, table `unified_messages` (read-only).

## Embeddings (verified, not assumed)
**We use one first-stage retriever: `qwen3`.** It is the default and the only current path. A
`cohere` retriever still exists in the code but is **archived** — kept for provenance/reproducibility
only (see "Archived: Cohere retriever" below), not used. `qwen3` became the default 2026-07-02 after a
bake-off on the two labeled event windows showed it matches or mildly beats Cohere; see
`qwen3-cohere-bakeoff-results` memory / commit history for the numbers.
- **`qwen3`** (the retriever we use): `qwen/qwen3-embedding-8b` via OpenRouter, **native 4096-d**, embedded
  plain for documents and with an `Instruct: {task}\nQuery: {text}` prefix for queries. Document
  vectors live in a float16 sidecar (~29GB) on **Neo**, a LAN box (see `neo-embedding-box` memory) —
  by design the sidecar and the dot-product scoring stay there; this machine only ships the tiny
  query matrix out and gets a small per-doc score tsv back, over SSH
  (`scripts/remote/neo_qwen_retrieve.py`, invoked by `matching.qwen_retrieve_remote()`). Built once
  from scratch by `scripts/backfill_embeddings_openrouter.py` — **full corpus coverage**
  (3,848,244 rows), not just the 2025 window. Needs SSH reachability to Neo + an OpenRouter key
  (for the query embedding call, which does run locally).
- **`cohere`** — **ARCHIVED, do not use for new work.** `embed-multilingual-v3.0`, **1024-d**,
  **`input_type=clustering`**, computed on the **`summary`** field, stored L2-normalized as JSON text
  in `unified_messages.embedding`. Confirmed empirically by the pipeline's space-check: re-embedding
  stored summaries reproduces the stored vectors at **mean cosine 0.989**. Coverage is ~4.9% of rows
  globally but **~89–100% for Feb–Apr 2025** — outside that window this retriever's pool collapses,
  which was the original motivation for the qwen3 from-scratch re-embed. The `--retriever cohere` code
  path is retained only so the pre-2025-07 bake-off/history remains reproducible.

## Method (two steps)
1. **Cosine retrieval.** Embed the event name + each quote + a combined string (a multi-probe query)
   with the selected retriever; score each pooled message by the **max cosine over probes**
   (favours recall for short colloquial quotes); keep top-`K` above a cosine floor.
2. **Rerank.** Cohere **`rerank-v3.5`** scores each candidate against an event query; keep
   `rerank_score >= threshold`. Always Cohere, regardless of retriever (rerank is embedder-agnostic —
   it scores query/document text, not the first-stage vectors). Then join media group, flag the
   keyword anchor, and export.

## Findings / gotchas (important)
- The `clustering` space has a **high cosine floor** (most unrelated pairs sit ~0.35–0.45), so cosine
  is a *weak* discriminator here — it mainly caps the candidate count, and the **rerank is the real
  precision gate**. Don't interpret raw cosine as relevance.
- The keyword anchor (`курск|судж`) is a **noisy superset (~4,658 in pool), not ground truth** — used
  only to estimate retention/leakage. Note: **SQLite `lower()`/`LIKE` is ASCII-only and silently
  misses capitalized Cyrillic** («Курск»), so keyword counting is done in Python.
- **653 in-window rows have empty-string embeddings** (all `vedomosti`); filtered via
  `embedding LIKE '[%'` so records and the vector matrix stay aligned.
- For this geographically-named event, genuine on-event coverage almost always names Kursk/Sudzha;
  only ~3 true non-keyword catches exist (операция «Поток» / «труба» without the place name), and they
  fall just below 0.35.

## Run
```bash
# full pipeline, qwen3 retriever (default; needs OPENROUTER_API_KEY + COHERE_API_KEY in .env)
.venv/bin/python scripts/build_event_dataset.py
# FREE re-threshold from saved candidates (no API calls)
.venv/bin/python scripts/build_event_dataset.py \
    --from-candidates data/processed/event_kursk_2025w11_candidates.csv --rerank-threshold 0.30
```
Reusable for other events via `--event/--year/--week` and `--days-before/--days-after`
(default window = ISO week −3 / +10 days, from `configs/project_paths.yaml`). Both the OpenRouter
and Cohere calls have automatic 429/5xx backoff.

## Outputs (`data/processed/`, gitignored)
| File | What |
|------|------|
| `event_<slug>_dataset.csv` / `.jsonl` | the kept messages (the dataset) |
| `event_<slug>_candidates.csv` | all reranked candidates + scores (the tuning surface) |
| `event_<slug>_review_sample.csv` | top + near-threshold rows for manual audit |
| `event_<slug>_manifest.json` | event, window, model ids, params, counts (provenance) |

Columns: `rank, source, media_group, message_id, date, is_digest, summary, original_message,
views, forwards, cosine_max, cosine_probe, rerank_score, keyword_match`.

## This run — Kursk / Sudzha, FOM 2025 W11 («Военные действия в Курской области», FOM 11%)
_(historical — built with `--retriever cohere`, before qwen3 became the default)_
- **Window:** 2025-03-07 … 2025-03-26 (ISO W11 = Mar 10–16, −3/+10).
- **Pool:** 43,075 embedded messages → 3,000 cosine candidates → **670 kept @ rerank ≥ 0.35**,
  across **42 sources and all 6 media groups**; coverage peaks **Mar 11–13** (the recapture).
- **Threshold guidance:** `0.35` precise (670) · `0.30` more inclusive (~940, adds genuine
  clearing/liberation coverage) · `0.40` strict (451, over-cuts real on-event messages).

## Caveats
- Recall is bounded by the cosine top-`K`. Strongly on-event messages have high cosine (0.70+), but
  for guaranteed recall on a geo-named event you can instead rerank the entire keyword set.
- `configs/media_groups.yaml` is a draft; one kept source is currently `uncategorized`.
