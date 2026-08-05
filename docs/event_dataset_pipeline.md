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
bake-off on the two labeled event windows (unbiased rerank-union labels, `scripts/bakeoff_embeddings.py`):
Qwen3 top-3000 recall **95.7% / 94.5%** vs Cohere **95.0% / 91.4%** — a mild but consistent Qwen3 edge.
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
   (favours recall for short colloquial quotes); keep everything above a cosine floor. `--top-k`
   can cap the count but defaults to no cap — see the note on the old cap of 3,000 below.
2. **Rerank.** Cohere **`rerank-v3.5`** scores each candidate **once per probe**, and each post
   keeps its best score; keep `rerank_score >= threshold`. Always Cohere, regardless of retriever
   (rerank is embedder-agnostic — it scores query/document text, not the first-stage vectors).
   `rerank_probe` records which probe won. Then join media group, flag the keyword anchor, export.

   Until 2026-08-03 this step used **one** query, made by gluing the event name and all the
   quotes into a single string (`--rerank-mode merged` still reproduces it). Measured over the
   3,000 candidates of the six pilot events, that glued query scored a post lower than any of
   its parts and reordered the list (Spearman 0.735–0.923 against the per-probe best). Worst
   single case found: a post about Russian and US diplomats meeting in Istanbul scored 0.867
   against the quote «встреча дипмиссий России и США» and 0.327 against the glued query, so it
   was excluded from «Налаживание контактов между Россией и США». «Рост цен, тарифов» went from
   0 kept posts to 27 on the same candidates.

## Findings / gotchas (important)
- **The old candidate cap of 3,000 was binding, so the counts were reading the cap.** With
  per-probe reranking, 2,235 of 3,000 candidates cleared the threshold on «Встреча Д. Трампа и
  В. Зеленского». Removing the cap raised that event from 1,368 kept posts to 3,124. The cap is
  now off by default; the cosine floor is the only limit.
- **Per-probe reranking can only add posts, never remove them,** because the glued query is
  itself one of the probes in near-identical form, so each post's best score cannot be lower
  than before. Measured: zero posts were dropped on any of the six events. It follows that the
  change cannot fix a false positive the old method had — it only raises recall.
- **How much of the growth is real depends on how specific the respondent quotes are.** Read by
  hand on 2026-08-03, 50 newly added posts per event (`data/interim/rerank_change_hand_labels.py`,
  which records the labels and the sampling seed): 94% on topic for «Военные действия в Курской
  области», 74–84% for the four diplomacy and prices events, and **32% for «Авиакатастрофа в
  Вашингтоне»**. That event's quotes are generic descriptions — «Авиакатастрофа в Америке»,
  «разбился авиалайнер в США» — and a different US air crash (a medical plane in Philadelphia)
  happened two days later inside the same window, so most of what was added is a different event
  of the same kind. Generic quotes plus a same-kind event in the window is the failure pattern
  to watch for.
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
views, forwards, cosine_max, cosine_probe, rerank_score, rerank_probe, keyword_match`.
`cosine_probe` is the probe that found the post in step 1; `rerank_probe` is the probe whose
score won in step 2. They are often different, and the pair is what makes a post's inclusion
traceable to a specific respondent phrase.

`scripts/audit_rerank_change.py` lines two builds of the same events up and prints the posts
they disagree on, in both directions, for reading by hand.

## Dataset naming in `data/processed/` (which file is which)

- **`event_*_qwen3_perphrase_*` — the current builds (2026-08-03).** Qwen3 retriever, no cap on
  the candidate count, one rerank query per probe with each post's best score kept. These are the
  only sets built with all three of those settings. Whether they should replace the earlier ones
  in the warehouse has not been decided — see the hand-labelled sample above, which found only
  32% of the newly added posts on topic for «Авиакатастрофа в Вашингтоне».
- **`event_*_qwen3_*` (no `perphrase`) — built 2026-08-03 earlier the same day.** Qwen3
  retriever, but still the 3,000-candidate cap and the single glued rerank query. This is what
  `scripts/load_warehouse.py` currently loads.
- **New events:** plain `event_<slug>_*`, built with the qwen3 retriever (the default).
- **Kursk is special — two sets exist side by side.** `event_kursk_2025w11_*` (no suffix) is the
  historical cohere-built set (670 kept, 2026-06-25); **all downstream framing artifacts for Kursk
  were extracted from it**, so it keeps its name for provenance. `event_kursk_2025w11_qwen3_*`
  (675 kept, 2026-07-01) is the qwen3 rerun of the same event, made for the retriever comparison.
- **`event_*_cohere_archived_*` — known-incomplete, do not analyze.** Four datasets
  (BRICS Kazan 2024-W43, Putin Direct Line 2024-W51, Sevastopol beach 2024-W26, Trump
  inauguration 2025-W04) were built 2026-06-28 with the cohere retriever *outside* its
  Feb–Apr 2025 coverage window, so their candidate pools had collapsed (e.g. BRICS: 43 kept
  while ~2,000 keyword hits existed in the window; Direct Line: 16 kept). They are kept only
  as a record of that mistake; rebuild with `--retriever qwen3` before using these events.

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
- `configs/media_groups.yaml` is a draft grouping, but no source is unassigned any more. Since
  2026-08-03 all 84 sources are either in one of the six groups (56 sources) or in the `archived:`
  block (28 sources, out of scope: regional outlets and channels that are not news media). The
  builder drops archived sources from the candidate table after reranking and records how many it
  dropped as `archived_candidates_dropped` in the manifest.
