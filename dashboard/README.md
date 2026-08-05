# Dashboard Notes

## What is here now

A working **prototype** of the coverage dashboard, built on the real matched post sets in
the warehouse. It stands in for Metabase: same numbers, same drill-down, but as one
self-contained HTML file that opens by double-clicking, with no server and no network.

- `coverage_dashboard_template.html` — the page itself (layout, charts, interaction).
  It contains a single `__DATA__` placeholder where the mart data is injected.
- `build_dashboard.py` — fills the placeholder and writes the finished file to
  `outputs/dashboard_exports/coverage_dashboard.html` (untracked; rebuild it locally).

Nothing here queries the warehouse directly. The page reads a snapshot exported by
`scripts/export_dashboard_data.py`, which selects exactly the mart tables a live Metabase
dashboard would read. When Metabase takes over, both the export script and the template
can go; the dbt marts underneath them are the part that stays.

## Rebuilding it

Four steps, in order, from the repository root:

```sh
.venv/bin/python scripts/load_warehouse.py            # raw tables into DuckDB
cd dbt && ../.venv/bin/dbt build && cd ..             # models + tests
.venv/bin/python scripts/export_dashboard_data.py     # marts -> JSON snapshot
.venv/bin/python dashboard/build_dashboard.py         # JSON + template -> one HTML file
```

`dbt build` should end with no warnings. The one test that warns rather than fails,
`warn_events_built_on_nonstandard_settings`, names any event whose matched set was built on
settings that make its count non-comparable — see the note below.

## What it shows

Five events, 4,108 matched posts, seven media groups (six named plus one bucket of sources
that are not assigned to a group yet).

Across all events: survey share against matched post count, and which events the public
named more often than the media covered.

For a selected event: the respondent quote examples, coverage volume by media group, the
same coverage divided by everything that group published in the window, how much of the
group actually turned to the event, who published first and how long after the window
opened, coverage day by day, every number in a table, and the individual posts behind any
bar.

Across events, comparing the groups with each other: which events landed with which kinds of
media, and with their audiences. Each cell compares a group against its own average across
all loaded events, because raw counts would only ever rank the groups by size.

For a selected event, the vocabulary: the words and phrases one group used that the other
groups covering the same event did not, with the posts behind each one a click away.

The original list on this page asked for an event selector, the survey percentage and quote
examples, coverage volume by group, first-mention timing, top terms by group, and sample
matched posts for audit. Everything on that list is now in the prototype.

## Two things the prototype deliberately makes visible

**Silence is measured, not assumed.** Every group publishing anything during a window
appears in the charts, including groups with zero matched posts, with a count of what they
did publish instead. "Said nothing about this event" and "was not publishing" are
different rows, not the same blank space.

**Where a count cannot be trusted, the page says so and shows the numbers.** Two separate
things can make an event's total wrong, and the page checks each one per event rather than
merging them into a vague quality score: posts kept at a lower relevance score than 0.35,
which makes the total too high, and a search that could not reach the whole window, which
makes it too low. No event carries either warning at the moment — all five were rebuilt on
2026-08-03 at 0.35 over their full windows — but the check stays in the page, so an event
added later on different settings cannot slip into the comparison unmarked. Comparisons
between groups *inside* a single event were never affected either way, because every group
was searched the same way.

The older advice on this page — do not build a complex interface before the matching
quality has been checked on a sample — is why the relevance score sits on every post, why
the average score per group is in the table, and why the drill-down is one click from every
chart. The audit path is part of the interface rather than a separate exercise.

## Word counting is not framing analysis

The vocabulary section reports which words appear where. It makes no claim about tone,
stance or intent, and it uses no model — it is counting, done in SQL, with the posts behind
every number one click away. Framing and narrative extraction remain out of scope for this
phase; the difference is that framing asks what a text is *doing*, and this asks only which
words are *present*.

Getting it to say anything useful took three filters, because the first version returned
almost nothing but channel furniture — "прислать новость", "rybar поддержать", "whatsapp
youtube рассылка". A word is listed only if at least two channels in the group used it, if
no single channel accounts for more than 70% of the posts carrying it, and if the group used
it more in this event than in its coverage of the other events. The reasoning for each is at
the top of `dbt/models/marts/event_group_terms.sql`.

## Not in the prototype

A live warehouse connection instead of an exported snapshot (that is what the Metabase setup
in `metabase/` is for); a group map that is correct for the date of the event rather than for
today; and framing or narrative comparison.
