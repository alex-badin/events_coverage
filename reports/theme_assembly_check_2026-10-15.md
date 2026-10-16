# Do cross-week themes hold together across periods?

Check run on 2026-10-15. Question: when every FOM survey event is given a theme (a subject
that recurs across weeks, such as prices or the war), does the same subject land in the same
theme in different weeks and years, even though FOM words it differently over time?

Terms. A *specific event* is a named event on a weekly FOM list; FOM's catch-all rows («Другие
события в России») and the "could not answer" row are left out. A *wording* is FOM's text for an
event, with spelling variants merged (ё/е, quotes, letter case): 1,031 exact spellings make 1,024
wordings. Themes sit in 7 *areas* of news (war, the world, domestic politics, the economy, health,
incidents, society); each area also has an "Other …" catch-all for subjects that do not recur, so
there are 46 themes in all: 39 named ones and 7 catch-alls.

## Answer

Yes, for nearly all of the data. The themes connect almost every survey event to other
events on the same subject in other years, mostly through *different* FOM wordings. That is
the part a plain name match cannot do.

| Base: the 2,772 specific events in 248 FOM survey weeks, 2020-W02 to 2025-W11 | Events | Share |
|---|---:|---:|
| Its wording also appears in another calendar year (a name match alone) | 967 | 34.9% |
| It is in a named theme (not an "Other …" catch-all) that also holds a *different* wording from another calendar year | 2,702 | 97.5% |
| It is in a named theme, not in an "Other …" catch-all | 2,720 | 98.1% |

| Base: the 39 named themes (of 46; the 7 catch-alls excluded) | Themes |
|---|---:|
| Members in 3 or more calendar years | 33 |
| Members in 2 calendar years | 5 (flu, internet restrictions, migrants, mobilisation, sanctions) |
| Members in 1 calendar year | 1 (Prigozhin and the Wagner mutiny, a single 2023 episode) |

The independent check found no label that breaks the written rules. Where a subject did split
across periods, the cause was one of three things: a rule that was wrong; a generic FOM rubric
that holds a different subject in different weeks; or FOM changing how it split its rows between
waves, which the "first-named subject decides" rule then followed. The first two were fixed where
the evidence was clear; the cases marked "Not changed" in the table below are mostly the third.

## How it was done

1. **Theme list.** Three Claude agents each proposed themes from the 1,024 distinct FOM
   wordings, each from a different angle. A fourth agent merged the proposals into
   `configs/fom_theme_taxonomy.json`: definitions, boundary rules, 21 families of wording
   variants, and 16 wordings whose meaning changes over time.
2. **Labels.** OpenAI Codex (`gpt-6.1-sol`, effort medium) gave each wording one theme, in 21
   calls of up to 50 wordings, all on the same model.
3. **Independent check.** Nine Claude agents that had not built anything:
   - four re-read every label, split by area (one or two areas each; 1,024 wordings in all);
   - three hunted for subjects split across periods, by timeline, by recurring names and places,
     and by reading the per-week respondent quotes of long-running wordings;
   - two then tried to refute every reported problem by re-reading the data.
4. **Fixes and relabel.** The rules the check proved wrong were changed. Codex relabelled all
   1,024 wordings, and five survey rows got a week-level override.

## What the check found

57 problems were reported. The two skeptics rejected 34 as defensible under the rules, either
way or as a matter of taste: 19 "ambiguous", 8 "theme too broad", 4 "missing theme", 3 "split".
They confirmed 23, which come down to nine causes:

| Cause | Confirmed reports | Survey rows affected | What was done |
|---|---:|---:|---|
| A rule exception with a false premise moved FOM's 2023 relations-with-the-West rubric to "Western weapons", which left that theme with only 6 survey weeks in 2023 | 3 | 19 (2023-W03..W39) | Exception removed; relabelled to relations |
| The nuclear-war scare went to two themes depending on which subject FOM named first (autumn 2022 vs 2024) | 1 | 3 | Rule: any mention of nuclear war → the nuclear theme |
| FOM folded COVID restrictions into its main COVID row in some waves but not others, so restrictions alternated between two themes | 2 | 45 | The two COVID themes merged into one |
| A generic rubric holds a different subject in one week (Victory Day 2021 inside «Праздники, памятные даты»; Leningrad 2024; a US hurricane inside «Стихийные бедствия»; the US freeze inside «События в США») | 10 | 5 | Week-level overrides in `dbt/seeds/fom_event_week_themes.csv`, with the reason for each |
| Two recurring subjects sat in "one-off" buckets: space flights (3 years) and flu (2 winters) | 2 | 13 | New themes |
| 1 September and the last bell sit in the holiday rubric in some years and in education in others | 2 | about 6 | Not changed: those weeks' holiday rows also carry other holidays |
| Sanctions are mentioned inside the relations rubric, so the sanctions theme has 23 of its 24 weeks in 2022 | 1 | — | Not changed: follows the rule; the theme description says so |
| FOM's merged 2022 row «Преступления, несчастные случаи» goes to crime although most of its quotes are accidents | 1 | 5 | Not changed |
| Putin's foreign trips go to "Putin" or "summits" depending on FOM's wording, May–July 2024 | 1 | 2 | Not changed |

## How stable the labels are

- **Two labellers, same rules.** The agent that merged the theme list also placed every
  wording itself, as a check on its rules. That Claude labelling and the first Codex run agree
  on 1,021 of the 1,024 wordings.
- **The same labeller twice.** After the fixes, Codex relabelled all 1,024 wordings from
  scratch. The two runs differ on 33 wordings (80 survey rows), and all 33 are the changes the
  fixes asked for. The other 991 wordings got the same theme both times.
- **Confidence field.** Codex marked every label "high" confidence, so that field says nothing
  and the seed no longer carries it.

## Limits

- Every reviewer here is a language model. No person has labelled a sample, so this measures
  whether the labels follow the written rules and stay consistent, not whether the rules match
  how a person would group the news. The theme table on the dashboard shows every FOM wording
  a theme groups, so a reader can check.
- One theme per wording is right for nearly every row, but generic FOM rubrics can change
  subject from week to week. Five rows are corrected by hand today; new survey weeks can add
  more.

## Found on the way: one misdated survey week in the source data

The FOM rows filed under 2022-W22 (30 May – 5 June 2022) describe late July 2022. They include
Navy Day, Putin's visit to Iran, Lavrov's Africa tour, the seventh sanctions package and
Rogozin's dismissal. There are no rows for 2022-W30 (25–31 July). So 13 survey rows sit eight
weeks too early on every timeline, and the real 2022-W22 list is missing. The fault is in
`fom_events/processed_events/events_table.csv` (or the report it was parsed from), which is a
read-only raw input here, so it was reported rather than patched.

Fixed 2026-10-17. The PDF at FOM's `d22sn2022.pdf` address is the issue for the 29–31 July
2022 survey, and the week came from that address number. The step that builds the table
(`fom_events/events_analysis.ipynb`) now files that issue under 2022-W30, so the 13 rows
moved there. The real 2022-W22 list is still missing.

## Files

- Rules: `configs/fom_theme_taxonomy.json`
- Labels: `dbt/seeds/fom_event_themes.csv`; week-level overrides: `dbt/seeds/fom_event_week_themes.csv`
- Labelling code: `scripts/fom_themes.py`, `scripts/run_theme_labelling.sh`
- Prompts, answers and logs of both runs: `data/interim/themes/labels/` (not in git)
