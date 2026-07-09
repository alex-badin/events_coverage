# Framing methodology — dimensions and pipeline

This note explains **every dimension** the pipeline extracts (where it comes from, what it means, its
possible values) and the **step-by-step path** from a raw news message to a cross-group framing
comparison. For the operational/CLI view see [`framing_pipeline.md`](framing_pipeline.md).

## 1. Core principle: two layers

Because the news texts are *already matched to one event*, they **share the facts** — the same
entities and actions. The analytic signal is not the facts but the **interpretation** laid over them.
So each message is decomposed into two layers:

- **Shared substrate** — *what happened* (entities, actions), kept group-neutral. This is the common
  grid that lets us line up coverage and detect "same actor, opposite role".
- **Framing / interpretation** — *how it is told*. This is where media groups differ, and it is the
  thing a summary destroys. We capture it as typed fields so stance/tone survive aggregation.

A **narrative** is then a recurring *configuration* of the interpretation layer (problem + cause +
roles + labels), induced bottom-up — not a predefined list.

## 2. Dimension reference

Every interpretive field also carries a **verbatim `evidence` quote** (its provenance guard).
Theory sources: **Entman (1993)** "Framing: Toward Clarification of a Fractured Paradigm" (the four
framing *functions*); **Semetko & Valkenburg (2000)** "Framing European Politics" (five generic
frames); narrative **character roles** (Propp's *dramatis personae*; the victim–villain–hero triad
used in framing/propaganda studies, cf. SemEval-2025 entity framing); **stance/evaluation** (Du Bois'
"stance triangle"); **evidentiality / epistemic stance** (Aikhenvald) plus journalistic attribution
norms; **lexical framing** (framing-by-word-choice); **selection & salience** (Entman; agenda-setting,
McCombs & Shaw).

| # | Field | Layer / source | What it captures | Possible values | Kursk example |
|---|-------|----------------|------------------|-----------------|---------------|
| 1 | `entities[]` | Substrate · actor detection (NER) | the cast of actors named | `mention` (RU surface), `canonical` (EN, merged), `type` (military/state/person/place/org/group/…) | ВС РФ / наши бойцы → **Russian Armed Forces** |
| 2 | `actions[]` | Substrate · event/role extraction | what happened, group-neutral | `predicate`, `agent`, `target` | strike · agent=Russian forces · target=Sudzha |
| 3 | `problem_definition` | **Entman fn 1** — define the problem | what the event *is* framed as | short English gloss | "liberation of Russian territory" vs "Russian assault on a town" |
| 4 | `causal_attribution` | **Entman fn 2** — diagnose cause | who/what is presented as the cause | `cause_entity`, `mechanism` | cause = Ukraine (prior occupation) vs cause = Russia (unprovoked) |
| 5 | `moral_evaluation[].role` | **Entman fn 3** + narrative roles | the dramatic part an actor is cast in | controlled inventory: aggressor, defender, liberator, occupier, victim, perpetrator, hero, villain, provocateur, ally, mediator, protector, threat, beneficiary, traitor, neutral_actor, bystander, other | Russian forces = **liberator/hero**; Ukrainian forces = occupier / villain / victim (by outlet) |
| 6 | `moral_evaluation[].polarity` / `.intensity` | Stance triangle (evaluation) | evaluative loading toward that actor | `polarity` −2…+2 (valence), `intensity` 0…2 (strength) | Russian forces +2 / 2 in war channels |
| 7 | `treatment` | **Entman fn 4** — suggest remedy | the prescribed action/response | free text or `null` | "continue the offensive" · often `null` |
| 8 | `epistemic_status` | Evidentiality + attribution | *how* the core claim is presented | `asserted` (own voice) · `attributed` (sourced) · `hedged` · `denied` · `questioned` | war channels **assert** «освобождение»; state agencies **attribute** to MoD |
| 9 | `emphasized[]` | Selection & salience (Entman; agenda-setting) | what the text foregrounds | list of short phrases | "heroism of pipeline maneuver" vs "civilian suffering" |
| 10 | `action_labels[]` | Lexical framing (word choice) | the loaded word chosen for the action | `term` (RU verbatim), `valence` ∈ positive/negative/neutral | «освобождение» (+) vs «оккупация»/«теракт» (−) vs «наступление» (neu) |
| 11 | `semetko` | **Semetko & Valkenburg (2000)** | which generic news frame(s) are active | 5 booleans: `conflict`, `human_interest`, `economic_consequences`, `morality`, `responsibility` | independent ↑ human_interest; war channels ↑ conflict + responsibility |
| 12 | `*_evidence` | Faithfulness / provenance | verbatim quote backing each tag | RU quote (fuzzy-matched back into source) | `problem_definition_evidence` = "…освободили Суджу…" |
| 13 | `on_event` | Relevance guard | is this message really about the event? | bool (+ evidence) | guards digests |
| 14 | `narrative_id` | **Induced** (narrative theory) | a recurring *configuration* of 3–11 | per-event labels (≤8), discovered not predefined | "Sudzha freed from occupation"; "Potok as failed/detected attack" |

The controlled vocabularies (roles, epistemic values, Semetko definitions) live in
[`configs/framing_schema.yaml`](../configs/framing_schema.yaml) and are the editable instrument; the
Pydantic enums are built from that file.

## 3. Pipeline, step by step (raw text → comparison)

**Step 0 — Input.** One row = one Telegram message already matched to the event by the matching
pipeline (cosine + rerank). For Kursk: 669 messages, 6 media groups.

**Step 1 — Normalize text** (`framing.normalize_text`). Use `original_message` (never the pre-computed
`summary`, which has already flattened tone); unwrap Telegram JSON blobs (`{"_":"Message",…}` →
`.message`); truncate to 2,000 chars → `text_used`.

**Step 2 — Extract framing** (`extract_framing.py` → `gpt-5.5`, strict Structured Outputs). One call
per message produces the record of §2 (substrate + all framing fields + evidence). → `…_framing.jsonl`.

**Step 3 — Canonicalize entities.** One LLM pass merges name variants (ВС РФ / российские войска /
наши бойцы → "Russian Armed Forces") so role aggregation doesn't fragment (Kursk: 988 → 786 distinct).

**Step 4 — Faithfulness** (`faithfulness.py`). Each `evidence` quote is fuzzy-matched back into
`text_used`; quotes that don't occur are flagged as fabrications (provenance score per record). An
optional `gpt-5.5` LLM-judge spot-checks that roles/labels are actually supported.

**Step 5 — Induce narratives** (`induce_narratives.py`) — see §4.

**Step 6 — Compare across groups** (`compare_framing.py`, pure pandas). Everything normalized **within**
media group (never raw counts), every share with a **bootstrap 95% CI**: narrative×group matrix,
pairwise **Jensen–Shannon divergence**, entity-role contingency + **role-flip** detection (flagged when
a role's valence sign flips across groups), epistemic / Semetko / causal / action-label breakdowns,
and an omission matrix. → CSVs + heatmap + `reports/…_framing.md`.

## 4. How narratives are revealed (Step 5 in detail)

The key move: **cluster on the framing, not the text.** The matched messages are already similar, so
clustering raw text (or its embedding) collapses them into one blob; the framing variation is a thin
layer that text similarity averages away. So:

1. **Signature** — build a compact fingerprint per message from the interpretation layer:
   `problem_definition · action-label terms · cause · (entity→role)* · epistemic_status`.
2. **Embed** the signatures (Qwen3 `qwen/qwen3-embedding-8b`, 4096-d, with a symmetric clustering
   instruction — switched from Cohere 2026-07-08 so the project uses one embedder).
3. **Cluster** (HDBSCAN; one event's signatures are near-duplicates and can collapse to all-noise,
   so we **fall back to KMeans** purely to seed diverse exemplars).
4. **Induce taxonomy** — `gpt-5.5` reads each cluster's exemplars and proposes **≤8 named narratives**
   (merging near-duplicates, keeping opposed framings separate).
5. **Reclassify** — every message is assigned to one narrative in that fixed taxonomy → stable
   `narrative_id`, which is what Step 6 compares.

The narrative labels are a *per-run lens* (induction is stochastic and granularity grows with sample
size — Kursk found 3 narratives at 328 messages, 5 at 669). The **per-message framing fields** (roles,
epistemic status, labels) are the stable substrate; treat them, not the narrative names, as ground.

## 5. Scales and faithfulness
- `polarity`: integer −2…+2 (−2 very negative, 0 neutral, +2 very positive) toward the entity.
- `intensity`: integer 0…2 (0 weak … 2 strong).
- Faithfulness for Russian uses **evidence-span provenance + LLM-judge** (MiniCheck/AlignScore are
  English-trained). Kursk provenance: mean 0.951, 69% of records perfectly grounded.

## 6. Limitations
- Roles/labels reflect the text's *surface* framing; when an outlet *quotes* a side, that quoted frame
  is captured — `epistemic_status` (attributed/hedged) is what separates "relays a claim" from
  "asserts it." For Kursk this is exactly why the divergence is mostly **epistemic**, not role-reversal.
- `causal_attribution.cause_entity` leans toward "the active agent," which can read as agency rather
  than blame; interpret alongside `moral_evaluation`.
- Narrative taxonomy is per-event and stochastic (see §4). For longitudinal/cross-event comparison,
  rely on the fixed layers (Semetko frames, role inventory, epistemic enum), not narrative names.
