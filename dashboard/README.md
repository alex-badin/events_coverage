# Dashboard Notes

## What is here now

A working **prototype** of the coverage dashboard, built on the real data in the warehouse.
It stands in for Metabase: same marts, same drill-down, but as one self-contained HTML file
that opens by double-clicking, with no server and no network.

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
cd dbt && ../.venv/bin/dbt build && cd ..             # seeds, models + tests
.venv/bin/python scripts/export_dashboard_data.py     # marts -> JSON snapshot
.venv/bin/python dashboard/build_dashboard.py         # JSON + template -> one HTML file
```

`dbt build` should end with no warnings. Two tests warn rather than fail:
`warn_events_built_on_nonstandard_settings` names any event whose matched set is not
comparable with the others, and `every_specific_event_has_a_theme` names survey events whose
wording has no theme yet (see `dbt/seeds/README.md` for how to label them).

## How it is organised

The page is built for many survey weeks, of which only some will ever have measured coverage:
the survey exists for 249 weeks (2020–2025), while a matched post set is built one event at a
time and costs money. Today 5 events have one, all between late January and March 2025.

Two views, switched in the top bar, and one panel. Every state is in the address
(`#/`, `#/umbrella/<id>`, `#/theme/<id>`, `#/week/2025-W10/<event_id>/<group_key>`), so the
browser's Back button works and any view can be linked.

**Overview — across all weeks.**
1. A status line: how many weeks and events the survey covers, how many events have measured
   coverage, and the date the news data ends.
2. *What people noticed, week by week*: a heatmap, one row per area of news, one column per
   calendar week. Colour is the survey attention that week; weeks with no survey are hatched;
   a strip on top marks the weeks with measured coverage. Clicking an area opens its themes;
   clicking a week opens it.
3. *How this theme was put together* (only with an area or theme selected): every FOM wording
   grouped into it, with the weeks it was named. This is where a reader can check that a theme
   really holds one subject across the years.
4. *Coverage measured so far*: one row per measured event, one column per media group, each
   cell the group's matched posts per 1,000 of its own posts in the event's window. The last row
   adds the events up with each post counted once.

**Week — one survey week.**
1. A header to step through weeks (the arrows skip weeks without a survey) or jump to any of
   them, with links to the nearest weeks that have measured coverage.
2. *What people named this week*: every event on the week's list, by share, with its theme and
   whether its coverage is measured.
3. The selected event: share, theme, respondent quotes, and a warning if its numbers cannot be
   compared with other events.
4. *How each media group covered it*: one bar per group, one measure. Day-by-day coverage, a
   table of every number and how the posts were matched sit in a closed section below.
5. *The posts behind the numbers*: filter by group, then by the words that group used more
   than the others; every post carries its relevance score.

**About the data** — one panel for everything that used to be spread over the page as notes:
what the survey measures, how themes were made, what counts as coverage, the three kinds of
zero, the warning rules, the media grouping, and the end date of the news data.

## Things the page keeps visible on purpose

**Silence is measured, not assumed.** A group that published nothing on an event still
appears, with what it did publish; "0 of 1,432 posts", "not publishing in this window" and
"fewer than 5 posts" are three different cells, not one blank.

**Not measured is not zero.** An event without a matched post set reads "not measured yet",
never 0.

**Each post is counted once.** Search windows of neighbouring weeks overlap, so a post can be
matched to two events. Every total over several events counts it once and divides by what the
group published over the days the windows cover, each day once (`theme_group_coverage`).

**Mentions are not people.** A theme's or area's survey value adds its events' shares. One
respondent can name two events of one theme, so the page calls it "mentions per 100
respondents", never a percentage of people.

**Where a count cannot be compared, the page says so.** An event built below the standard 0.35
relevance score, or whose search could not reach the whole window, carries a ⚠ and the reason.
No loaded event carries one today; the check stays so a later event cannot slip in unmarked.

## Word counting is not framing analysis

The word chips under the posts report which words appear where. They make no claim about tone,
stance or intent, and use no model — it is counting, done in SQL, with the posts behind every
number one click away. The rules that keep out channel sign-offs are at the top of
`dbt/models/marts/event_group_terms.sql`.

## Not in the prototype

A live warehouse connection instead of an exported snapshot (that is what `metabase/` is for);
a group map that is correct for the date of the event rather than for today; and framing or
narrative comparison.
