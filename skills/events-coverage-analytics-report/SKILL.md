---
name: events-coverage-analytics-report
description: Evidence-backed analytical reporting workflow for the events_coverage project. Use when working in the events_coverage project and the user asks to summarize, present, compare, report, or revise results from media-coverage, event-matching, framing, narrative, source-group, dashboard, chart, or pilot analysis. Forces Data Analytics build-report, visualize-data, and validate-data rather than prose-only summaries, and prohibits unsupported comparative language.
---

# Events Coverage Analytics Report

## Overview

Use this skill to turn `events_coverage` analysis artifacts into an evidence-backed reader-facing report. The skill exists to prevent vague analytical prose: every important comparison must name the metric, base count, denominator, comparison set, magnitude, and visible supporting table or chart.

## Required Companion Skills

When this skill triggers for a report or substantial summary, also use the Data Analytics workflow:

- `data-analytics:build-report` for the report shape and delivery.
- `data-analytics:visualize-data` for chart and table selection.
- `data-analytics:validate-data` before handoff.

Do not hand off a chat-only narrative unless the user explicitly asks for a quick informal note.

## Source Files

Verify required inputs are readable before downstream work. Prefer these project artifacts:

- `data/interim/event_*_framing.jsonl` for per-message framing labels.
- `data/processed/event_*_manifest.json` for event windows, model settings, and dataset counts.
- `data/processed/event_*_dataset.csv` for matched messages and media groups.
- `outputs/event_*_*.csv` for computed comparison tables.
- `reports/README.md` and `reports/event_*_framing.md` for existing readouts.
- `configs/media_groups.yaml` for source grouping, noting that it is draft analytical grouping.
- `docs/framing_readout_caveats.md`, `docs/framing_pipeline.md`, and `docs/event_dataset_pipeline.md` for method caveats.

Keep raw input data unchanged. Write any new derived report data to `data/interim/`, `data/processed/`, `outputs/`, or `reports/` only when the user asks for a durable artifact.

## Claim Standard

Before drafting, make a claim ledger. For each planned finding, record:

- claim text
- metric and formula
- event, date window, and included records
- denominator and base counts
- comparison set or baseline
- magnitude of difference
- uncertainty or caveat
- table or chart that will show the evidence

Do not use analytical comparison words unless this ledger has the needed support. Guarded words include `outlier`, `largest`, `smallest`, `higher`, `lower`, `more`, `less`, `dominant`, `stronger`, `weaker`, `different`, `clearest`, `meaningful`, `significant`, and `directional`.

Use this sentence shape for important comparisons:

```text
<Group/segment> is <comparison> on <metric>: <value> (<count>/<denominator>) versus <baseline/range/next group>, a <difference> gap.
```

Bad:

```text
Independent media were the clearest outlier.
```

Good:

```text
Independent/exile media had the lowest positive action-label share in Kursk: 29% of loaded action labels, compared with 58%-68% for the other five groups.
```

## Evidence And Visuals

For each major finding:

- Show all relevant groups, not only the highlighted group.
- Use counts and percentages together when sample size affects trust.
- Put the denominator in the table, chart subtitle, or nearby paragraph.
- Explain distance metrics such as Jensen-Shannon divergence with their scale and peer values. Do not say "largest distance" without showing the distance table or range.
- If a group has small volume, label the result as directional near the finding. As a default, avoid strong group-level claims when `n < 30`, and avoid comparing groups with `n < 15` unless the report is explicitly exploratory.
- Put caveats next to the affected chart or table, not only at the end.

Prefer these report visuals:

- grouped or horizontal bars for group percentages and counts
- heatmaps for narrative-share matrices
- ranked bars or tables for divergence and top/bottom comparisons
- tables for exact audit detail, base counts, and small samples

## Report Shape

Use a report, not a dashboard grid, unless the user asks for exploration.

Minimum structure:

1. Title.
2. Executive summary with 2-4 evidence-backed bullets.
3. Scope and evidence base: events analyzed, records included, date windows, media groups, and unfinished artifacts excluded.
4. Key findings, each with nearby table or chart plus interpretation.
5. What is solid versus exploratory.
6. Caveats that could change interpretation.
7. Recommended next analysis step.

The report is not ready if the reader must trust hidden calculations or infer what a comparison means.

## Validation Gate

Before handoff, validate the report:

- Every major claim has visible evidence.
- Every percentage has a denominator or nearby base count.
- Every "more/less/largest/outlier" statement names the metric and comparison base.
- Tables and charts match the narrative text.
- Caveats are attached to the specific finding they qualify.
- Unfinished datasets are not described as completed analyses.
- The final answer points to the report artifact and supporting files, not a substitute prose summary.
