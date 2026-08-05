# Single-event framing comparison pipeline

Compares **how** different media groups frame *one* already-matched event — not the facts (those are
shared across matched coverage) but the interpretation: which role each actor is cast in, how an
action is labelled, who is blamed, and whether claims are asserted or merely attributed. It is
**structure-first** (extract typed framing fields, then aggregate) so stance/tone survives instead of
being flattened by a summary. Runs on top of the matching pipeline
([`event_dataset_pipeline.md`](event_dataset_pipeline.md)).

## Inputs
- A single-event dataset CSV from `build_event_dataset.py`:
  `data/processed/event_<slug>_dataset.csv` (uses `original_message`, `media_group`, `is_digest`).
- The framing instrument: [`configs/framing_schema.yaml`](../configs/framing_schema.yaml) — Semetko &
  Valkenburg (2000) five generic frames, the entity-role inventory, and the epistemic-status enum.
  Edit this to change the instrument; the Pydantic enums are built from it.

## Model (verified, not assumed)
- Extraction: OpenAI **`gpt-5.5`** via **Structured Outputs** (strict json_schema backed by Pydantic),
  reasoning effort `low`. Needs `OPENAI_API_KEY` in `.env`.
- Measured cost ≈ **2,890 tokens/message**. With a **1M free-token/day** grant, a ~669-message event
  is a **~2-day job** — so extraction is resumable, budget-aware, and round-robin-balanced across
  media groups (a budget-limited partial stays balanced).
- Narrative clustering embeds signatures with **Qwen3 `qwen/qwen3-embedding-8b`** (4096-d, via
  `events_coverage.matching.embed_texts_qwen3` with a symmetric clustering instruction,
  `QWEN_CLUSTER_INSTRUCTION`). Switched from Cohere 2026-07-08 so the whole project uses one
  embedder; retrieval and clustering now share the qwen3 space.

## Method (three stages)

**1. Extract** — `scripts/extract_framing.py` (logic in `src/events_coverage/framing.py`).
Per message: normalize text (unwrap Telegram JSON blobs, truncate to 2,000 chars), then one
structured call → a `FramingAnalysis` record:
`entities`/`actions` (shared substrate) · `problem_definition` · `action_labels[term, valence]` ·
`causal_attribution` · `moral_evaluation[entity, role, polarity, intensity]` · `treatment` ·
`epistemic_status` · Semetko 5 frames · an `on_event` digest guard · a verbatim `evidence` quote on
every interpretive field. Optional entity-canonicalization pass merges name variants.
→ `data/interim/event_<slug>_framing.jsonl`.

**2. Induce narratives** — `scripts/induce_narratives.py`.
Build a compact framing **signature** per record (`problem_definition · label terms · cause ·
entity→role · epistemic`), embed with Qwen3, cluster (HDBSCAN `min_samples=1`, **KMeans fallback**
when the space collapses), have `gpt-5.5` consolidate cluster exemplars into **≤8 named narratives**,
then reclassify every message into that fixed taxonomy → stable `narrative_id`.
→ `…_narratives.jsonl` + `…_taxonomy.json`.

**3. Compare** — `scripts/compare_framing.py` (pure pandas, no API).
Everything normalized **within** media group (never raw counts) with **bootstrap 95% CIs**:
narrative×group share · pairwise **JS divergence** · entity-role contingency + **role-flip** detection
(flagged when a role's valence sign flips across groups) · action-label lexicon · epistemic / causal /
Semetko by group · entity-omission. → `outputs/event_<slug>_*.csv`, a plotly heatmap, and a
deterministic `reports/event_<slug>_framing.md`.

Faithfulness (`src/events_coverage/faithfulness.py`): evidence-span **provenance** (fuzzy-match each
quote back into the source — catches fabrications) plus an optional `gpt-5.5` **LLM-judge** on a
sample. MiniCheck/AlignScore are English-trained, so this substitutes for Russian.

## Findings / gotchas (important)
- **Cluster on the framing signature, never the raw text** — matched messages are already similar and
  collapse into one blob; the framing variation is a thin layer the text embedding averages away.
- Signatures for one event are near-duplicates, so density clustering can return all-noise/one blob;
  the KMeans fallback seeds exemplars and the LLM does the real consolidation. (This held for the old
  Cohere clustering space too — its high cosine floor made collapse especially likely.)
- `gpt-5.5` reasoning can consume the **entire** `max_output_tokens`, leaving a `None` parse;
  `framing.structured_parse` retries non-reasoning / chat variants — give classification calls a
  generous `max_output_tokens`.
- **Extract from `original_message`, not `summary`** — the stored summary is pre-flattened and has
  already lost the tone we are trying to measure.
- War/military sources store `original_message` as a Telegram JSON blob
  (`{"_":"Message",…,"message":"…"}`); `normalize_text` unwraps `.message`.
- `semetko_evidence` is a *rationale*, not a single verbatim span, so it is excluded from provenance.
- `action_labels.valence` is a strict `positive|negative|neutral` enum so the lexicon aggregates.

## Run
```bash
# smoke / Stage-1 gate (stratified sample is more informative than top-ranked rows)
.venv/bin/python scripts/extract_framing.py --input <stratified.csv> --slug kursk_smoke --workers 4

# Stage 1 full (resumable; budget-trims to fit the daily free grant; rerun to continue)
.venv/bin/python scripts/extract_framing.py --slug kursk_2025w11 --workers 4 --budget 950000
.venv/bin/python scripts/extract_framing.py --slug kursk_2025w11 --canonicalize-only   # optional merge

# Stage 2 + 3
.venv/bin/python scripts/induce_narratives.py --slug kursk_2025w11
.venv/bin/python scripts/compare_framing.py  --slug kursk_2025w11 --bootstrap 1000
```

## Outputs (`data/interim/`, `outputs/`, `reports/`)
| File | What |
|------|------|
| `data/interim/event_<slug>_framing.jsonl` | per-message framing records |
| `data/interim/event_<slug>_narratives.jsonl` / `_taxonomy.json` | records + induced narrative labels |
| `outputs/event_<slug>_narrative_by_group_ci.csv` | narrative×group share + bootstrap CIs |
| `outputs/event_<slug>_group_js_divergence.csv` | who frames most differently |
| `outputs/event_<slug>_role_flips.csv` | same entity, opposed roles across groups |
| `outputs/event_<slug>_{epistemic,semetko,causal,action_label_lexicon,entity_presence}_*.csv` | per-group breakdowns |
| `outputs/event_<slug>_narrative_heatmap.html` | narrative×group heatmap |
| `reports/event_<slug>_framing.md` | rendered comparison report |

## This run — Kursk / Sudzha (FOM 2025 W11), full 669 messages
- 6 media groups (Pro-gov 226 → War 49); 0 errors; provenance **0.951** (69% fully grounded);
  canonicalization merged 222 entity-name variants (988 → 786 distinct).
- 5 induced narratives: liberate Kursk settlements (351), Sudzha freed from occupation (159), Operation
  Potok heroic pipeline raid (129), footage confirms liberation (17), **Potok as failed/detected
  attack** (13, the contested counter-frame).
- **Independent/exile media is the framing outlier** (mean JS 0.28, highest); uniquely carries the
  contested narrative at **14% [CI 7–24%]** vs ≤2% elsewhere (non-overlapping CIs).
- **Epistemic split (the strongest, most stable signal):** war/military channels **assert** «освобождение»
  in their own voice (71%); state agencies **attribute** to MoD/РИА (87%); independent/exile
  **attribute/distance** (70%).
- **Role flip (🔴):** Ukrainian Armed Forces = victim (state agencies) vs villain (war/federal) vs
  occupier (pro-gov/independent/business). Russian Armed Forces do **not** flip (universal liberator/hero).
- **Partial-vs-full robustness:** a balanced 328-message partial reached the same conclusions; the
  epistemic axis and contested-narrative carrier were stable, while narrative-level JS distances were
  larger at the partial taxonomy (the dominant liberation frame is shared, so finer taxonomies dilute it).

## Caveats
- Narrative induction is **stochastic** and taxonomy granularity shifts with sample size (the partial
  found 3 narratives, the full 669 found 5) — treat narrative labels as a per-run lens, not a fixed
  registry; the per-message framing fields (roles, epistemic, labels) are the stable substrate.
- `configs/media_groups.yaml` is a **draft** grouping, not a final political label set. Note that the
  framing outputs in `reports/` predate the 2026-08-03 decision to archive 28 out-of-scope sources
  (regional outlets and channels that are not news media), so they may still contain posts from
  channels the current grouping excludes.
- For *this* event the divergence is mostly **epistemic**, not Russian-role-reversal; other events may
  show different axes — do not assume role-reversal is always the headline.
