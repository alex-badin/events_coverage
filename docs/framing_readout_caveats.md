# Reading the framing outputs — process & distortion caveats

How an aggregate value (e.g. a cell in the "Cast of actors" matrix) is produced from raw
gpt-5.5 output, and the two places meaning can be lost. Written after tracing two questioned
values back to source on 2026-06-29.

## The pipeline, end to end

1. **Match** (`scripts/build_event_dataset.py`): cosine retrieval + Cohere rerank over the
   embedded news pool for the event's ISO-week window → a kept set of messages, each tagged with
   `source` and `media_group`. Output: `data/processed/event_<slug>_dataset.csv`.
2. **Extract** (`scripts/extract_framing.py`): one gpt-5.5 Structured-Outputs call per message
   → one `FramingAnalysis` record. Output: `data/interim/event_<slug>_framing.jsonl`.
   **This jsonl is the raw, durable model output** — `text_used` (exact input text), `entities`,
   and the four Entman fields, each with a verbatim `evidence` quote.
3. **Read out** (scripts in `reports/generators/`): aggregate the jsonl into the HTML reports.
   No model calls here — pure pandas/Counter arithmetic.

A "Cast of actors" cell for (entity E, group G) is computed as:
> over all messages in group G, collect every `moral_evaluation` entry with `entity == E`;
> the cell's **role** = the single most frequent `role` (the mode); **stance** = mean `polarity`
> (clipped to −2..+2); **n** = number of such entries.

## Distortion #1 — the read-out compresses a distribution to its mode (analysis layer)

Showing only the modal role hides the spread, and can **invert** the picture:

- *Ukrainian Armed Forces, State agencies, Kursk*: modal role = `victim` (11) — but the full
  distribution is `victim 11, occupier 9, threat 8, aggressor 7, villain 7, perpetrator 5, …`.
  Condemning roles (36) dwarf `victim` (11). The cell label "victim" is the plurality of a
  fragmented negative distribution, not the story.
- *Zelensky, Independent/exile, Trump–Zelensky*: modal `provocateur` (11) barely beats
  `neutral_actor` (10); `victim` (4) also present. A near-tie shown as one definitive label.

**Fix when reading:** always pair the matrix with the full role distribution (raw explorer)
and never read role without polarity.

## Distortion #2 — role is assigned from framing *present in the text*, regardless of voice (input layer)

gpt-5.5 codes the role from the proposition in the message, **whether the outlet asserts it or
merely reports it**. `epistemic_status` records which — but the role/polarity does not fold it in.

- *Zelensky = provocateur* in Independent/exile (11 rows): **8 are `epistemic = attributed`** (the
  outlet quoting Trump — "Зеленский хочет воевать, воевать, воевать"), 2 `asserted`, 1 a
  rhetorical `questioned`. So independent outlets mostly **report** Trump's framing; the role
  field captures that framing all the same. Reading roles as the *outlet's* stance overstates it.

**Fix when reading:** filter or weight by `epistemic_status`; treat `attributed` role-castings as
"framing the outlet relayed," not "framing the outlet endorses."

## Known instrument defects that bite the read-out

- **`victim` is valence-ambiguous** (defeated enemy taking losses → `role=victim, polarity<0`).
  Only `role × polarity` disambiguates. See the codebook.
- **`intensity` is unbounded** (typed bare `int`) — ~23% of values exceed the documented 0–2.
- **`problem_definition` tracks shared facts, not stance.** For Kursk every group's gloss converged
  on "Russia regained Sudzha" even where roles diverged — independent coverage *relays* the
  operation. Evaluative divergence lives in roles/polarity, not problem_definition.

## Corpus boundary (caps how much divergence can exist)

All sources are Russian-language (state agencies → independent/exile). Detectable divergence runs
**state-celebratory → independent-neutral**, never the fully oppositional "Russia sabotages peace"
pole — that framing belongs to Western/Ukrainian outlets, which are not in the dataset.
See memory: `embedding-coverage-constraint`, `narrative-divergence-findings`.
