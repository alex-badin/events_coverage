# Project Instructions

This project analyzes how different media groups covered the same public events over a long historical period. The goal is not a daily news monitor. The goal is a structured historical dashboard that shows what each media group paid attention to, ignored, repeated, amplified, or framed differently.

## Communication Style

When explaining work, analysis, or results:

- use simple everyday words
- be a bit more detailed than the default
- explain what you did, what you found, and what you plan to do next when relevant
- prefer clear direct sentences over shorthand, jargon, or internal process language
- avoid tool names, abbreviations, and internal terms unless they truly help; if one is needed, explain it right away
- do not assume the user has the same context you built up while working
- when mentioning a file, command, or technical concept, add a short plain-language explanation if needed
- prefer short paragraphs; use lists only when they make the reply easier to scan

## Working Style

- Before doing downstream work, verify that any primary input file is readable. If a required file is missing, unreadable, or permission-blocked, stop and report the blocker; continue only if the user requested a fallback or the workflow explicitly supports one.
- Keep raw input data unchanged unless the user explicitly asks to rewrite or move it.
- Write cleaned or derived data to `data/interim/` or `data/processed/`.
- Write charts, dashboard exports, cached joins, and report outputs to `outputs/` or `reports/`.
- Prefer small, reproducible scripts over one-off notebook-only work when a step will be reused.
- If a step uses model-generated labels, keep the prompt, model name, date, and input/output path in the output notes.

## Current Primary Inputs

- `news_data/ask_media_unified_messages_20260604.db`: main historical media-message database. The main table is `unified_messages`.
- `news_data/ask_media_unified_messages_20260604_README.md`: notes about the news database build and columns.
- `news_data/ask_media_unified_basic_stats_20260604.md`: verified summary of news coverage volume, dates, and source counts.
- `fom_events/processed_events/events_table.csv`: default cleaned FOM weekly event table for analysis.
- `fom_events/downloaded_reports/`: source PDF reports used to create the FOM event table.

`fom_events/events_table.csv` is a working file and includes blank event names. Do not use it as the default analysis input unless the task is about debugging the FOM extraction process.

## Analysis Shape

The main workflow should be:

1. Normalize FOM weekly events into a clear event table.
2. Define a date window for each event, usually around the FOM week.
3. Find news messages that likely cover each event.
4. Group media sources using `configs/media_groups.yaml`.
5. Compare coverage by group:
   - share of voice
   - first mention and coverage lag
   - silence or under-coverage
   - repeated terms and narratives
   - framing differences
   - views and forwards when useful
6. Present results in a dashboard and, when useful, a short written finding.

## Cautions

- Do not treat keyword matches as proven coverage without checking examples.
- Do not treat source groups as final political labels unless the grouping file says they were reviewed.
- The news dataset has many summaries, but raw message text is only available for a smaller subset. Choose fields deliberately.
- The news data ends on 2025-04-02 in the current local snapshot. Do not describe results as current after that date.
- The project is for comparative media intelligence, not for judging factual truth of the covered events.
