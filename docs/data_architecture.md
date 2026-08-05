# Data Architecture — Events Coverage

Last updated: 2026-07-25

## Purpose

Historical media-intelligence: how different media groups covered the same public-agenda
events (FOM weekly reports) across 2018–2025. The MVP core is **coverage metrics**; framing /
narrative extraction is intentionally out of MVP scope (kept as an optional label producer).

The heavy analytical work (retrieval, rerank, framing) already exists as a Python pilot. This
blueprint describes packaging that pilot into a tested, orchestrated, queryable data product —
the data-engineering layer, not new NLP.

## Decisions (locked)

| Layer | Decision |
|---|---|
| Engine (phase 1) | DuckDB (local) |
| Transformations | dbt |
| Orchestration | Dagster |
| BI / visualization | Metabase |
| Embeddings | Qwen3, already computed (on the "Neo" box), ~$3.36 — sunk |
| Matching | embedding retrieval + Cohere `rerank-v3.5` |
| Framing (gpt-5.5) | out of MVP focus; optional per-message label producer |

## Data flow

```
[1] SOURCES (read-only)
      unified_messages (SQLite, 3,861,614 messages, 84 sources)
      fom events_table.csv (3,687 events, 2020–2025)
      configs/media_groups.yaml (source -> media group)
        |
        v
[2] RETRIEVAL — existing, Python, on the "Neo" box over SSH      (stays ML, not dbt)
      Qwen3 vectors (29.36 GB sidecar file, done) -> cosine, top-K=3000
        |
        v
[3] RERANK + THRESHOLD — existing, Python, Cohere rerank-v3.5    (stays ML, not dbt)
      keep rerank >= 0.35  ->  "kept" matched message set per event
        |
        v  (matched messages: 4,108 across the 5 usable pilot events — megabytes)
[4] LOAD -> DuckDB (phase 1, local)
        |
        v
[5] dbt TRANSFORM (in DuckDB):  staging -> intermediate -> marts  + tests + docs
        |
        v
[6] BI (Metabase):  event x media-group summary  -> click -> individual posts

Orchestration: Dagster ties [4]->[5]->[6] into one asset graph (dbt models appear as assets).
               Steps [2]/[3] run locally (need "Neo" over SSH — not cloud-portable).
Framing (gpt-5.5, per-message labels): OUT of MVP focus — optional input to [5].
```

## Components by layer

**[1] Sources (raw, read-only).**
- `unified_messages` (SQLite). Measured column sizes: `summary` 2.01 GB, `original_message`
  3.23 GB, archived `embedding` column 2.48 GB (190,426 rows, **unused — drop on load**).
  File on disk: 11 GB.
- FOM `events_table.csv`: 3,687 events (date / year / week / event / description / percentage).
- `media_groups.yaml`: hand-maintained source -> group map (draft — hence the tests below).

**[2] Retrieval (exists, Python, on "Neo").** Qwen3 vectors (`qwen/qwen3-embedding-8b`, 4096-d,
a 29.36 GB float16 sidecar file kept next to the corpus) live on the "Neo" LAN box; scoring runs
there over SSH, only the small query matrix leaves the machine. **Vectors never enter the
warehouse or BI.**

**[3] Rerank + threshold (exists, Python, Cohere).** `rerank-v3.5` prunes false positives; the
0.35 threshold yields the "kept" matched set per event. Cost is on the order of a few cents per
event at top-K=3000 (calculated) — keep the event set curated.

**[4] Load into DuckDB.** DuckDB can attach the SQLite directly (`sqlite_scanner`), so there is
no heavy migration. Load the needed message columns + events + group map. Optional: a
precomputed "posts per source per week" aggregate for denominators (small, computed once).

*Event scope.* Only events with a complete, current matched set are loaded — today that is 5 events
and 4,108 matched messages. The loader script holds the authoritative list; incomplete pilot
leftovers are named in the `AGENTS.md` cautions.

**[5] dbt transformations (in DuckDB).**
- **staging:** `stg_messages`, `stg_events` (derive window dates `match_start` / `match_end`
  from year+week; default -3/+10 days), `stg_media_groups`, opt. `stg_framing`.
- **intermediate:** `int_event_messages` — grain "one matched message in the context of an
  event" (message x event x media group x views/forwards).
- **marts:** `event_group_coverage` (grain: event x media group), `event_coverage_gaps`
  (grain: event — FOM attention % vs coverage volume), opt. `event_group_framing_shares`.
- **tests:** unique (event, source, message_id); not-null on keys; `accepted_values` on media
  group (only labels from `media_groups.yaml`); `relationships` (event_id exists in `stg_events`).
- **docs:** model dependency graph (dbt lineage) + column descriptions.

**[6] BI (Metabase).** Connects live to the database and reads the marts. Drill-down: click a
media group's bar on the summary -> a detail view lists that group's individual matched messages
for the event (date, source, text, views/forwards), optionally a link to the original post.

**Orchestration (Dagster).** Wires [4]->[5]->[6] into one visible asset graph, where nodes
(Dagster "assets") are the tables and dbt models in a shared dependency graph. Caveat: [2]/[3]
depend on "Neo" over SSH — those nodes are local and not cloud-portable.

## Core metrics (MVP)

All computed from the "kept" set in plain SQL, independent of gpt-5.5 (definitions in
`methodology.md`): `message_count`, `source_count`, `share_of_voice`, `coverage_presence`,
`first_seen`, `coverage_lag`, `views_total`, `forwards_total`.
Plus, from prior experiments, only the metrics that showed real group differences: external-link
share, editorial ("от себя") share.

## Storage sizing (measured)

- Core text `summary` + `original_message`: **~5.4 GB**; `summary` only: **~2.2 GB**.
- Data actually serving the dashboard (marts + matched detail): **megabytes** — 4,108 matched
  messages across the 5 usable pilot events, out of 16 dataset files in all, the rest being
  superseded or known-incomplete builds. All of `data/processed/` is 145 MB on disk.
- Qwen3 vectors 29.36 GB stay on "Neo" for now.
- Phase 1 (DuckDB local): size is a non-issue. Phase 2 (BigQuery): the text corpus fits under the 10 GB free tier. Qwen3 vectors - TBD.

## Built vs to build

- **Built:** retrieval, rerank, framing, per-event outputs, metrics (currently scattered CSVs in
  `outputs/`).
- **To build:** DuckDB load, dbt project (models + tests + docs), Dagster, Metabase dashboard.
- This is packaging an existing pilot into a tested, orchestrated shell — realistic in 1–2 weeks
  (closer to 2–3 with Dagster).

## dbt scope & staging

Staged so the MVP stays small and every later addition has a real reason in this data — not
features for their own sake.

**MVP (now):** the layers, tests, and docs already in [5] — `staging -> intermediate -> marts`,
generic tests (unique / not-null / accepted_values / relationships), and the docs site with the
model graph.

**Near-term depth (accepted, still on DuckDB):** the parts that turn a practice-level dbt project
into a real signal; each is tied to a genuine need here.
- **Incremental models** (a model reprocesses only new rows instead of rebuilding the whole
  history). Justified by scale — 3.86M messages over 7 years, FOM events arriving week by week;
  coverage models should process only new events / windows.
- **Snapshots (SCD Type 2)** (dbt keeps a dated history of how a row changed — a type-2 Slowly
  Changing Dimension). Applied to the `source -> media group` map: `media_groups.yaml` is a draft
  that will be revised, and real outlets shift alignment across 7 years, so "which group did this
  source belong to at event time" needs point-in-time-correct grouping, not a current-state join.
- **Unit tests** (run a model on small hand-made inputs and check the output; dbt >= 1.8).
  Intended for the metric math (share_of_voice, coverage_lag, window bounds), but the application
  here is still being designed — concrete example cases are deliberately NOT fixed yet.

**Next stage (planned, not MVP; still local unless noted):**
- **Seeds** — small reference CSVs loaded as version-controlled tables (`events_table.csv`,
  framing schema, possibly `media_groups`).
- **Sources + freshness** — declare `unified_messages` and FOM as sources so lineage starts at the
  true origin; optional staleness checks.
- **Exposures** — declare the Metabase dashboard as a consumer, so the graph shows the whole
  "raw source -> dashboard" chain.
- **Domain tests + packages** — `dbt_utils` / `dbt_expectations` for range checks (shares in
  [0,1], coverage_lag >= 0, no message dated outside its window).
- **Window macro** — a reusable Jinja snippet for the -3/+10-day window logic, so it is not
  duplicated across models.
- **Semantic layer / metrics (MetricFlow)** — define metrics centrally so they compute identically
  everywhere. Heavier, low payoff for a solo MVP — revisit only if the metric set grows.
- **Broader domain models** (e.g. richer framing marts) — kept deferred on purpose: this is the
  "feature inflation" direction the project must resist, so it stays a labeled future stage.

This "next stage" is separate from the cloud **Phase 2** below (DuckDB -> BigQuery); none of these
dbt additions require the warehouse move.

## Boundaries and risks

- Not a daily feed — a historical dashboard (infrequent refresh; see `methodology.md`).
- ML stays in Python — dbt only does the SQL aggregation around it.
- "Neo" dependency — retrieval is not cloud-portable (fine for a personal project).
- Event set must stay curated (rerank cost scales per event; all 3,687 events would run into the
  low hundreds of dollars).

## Phase 2 (deferred, out of this blueprint)

- Engine DuckDB -> BigQuery (closes the "cloud warehouse" gap; fits the free tier).
- Optionally host Dagster / Metabase on a cloud box (doubles as practical cloud-infra experience).
- Research agent-loop (an LLM judge that tests algorithms for narrative differences) — a separate
  later stage.

## Related docs

- Methodology and metric definitions: [methodology.md](methodology.md)
- Data inventory, embeddings provenance: [data_inventory.md](data_inventory.md)
- Single-event dataset pipeline: [event_dataset_pipeline.md](event_dataset_pipeline.md)
