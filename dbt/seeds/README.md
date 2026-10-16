# Seeds

Small reference tables kept in git and loaded with `dbt seed` (or as part of `dbt build`).

| File | What | Written by |
|---|---|---|
| `russian_stopwords.csv` | Words the vocabulary marts ignore | hand |
| `event_labels_en.csv` | Short English names for the events with a measured post set | hand |
| `fom_themes.csv` | The cross-week themes: 7 areas of news, 46 themes | `scripts/fom_themes.py seeds`, from `configs/fom_theme_taxonomy.json` |
| `fom_event_themes.csv` | The theme of every FOM event wording, one row per exact spelling, with the date and model that labelled it | `scripts/fom_themes.py seeds`, from model labels |
| `fom_event_week_themes.csv` | The few survey rows whose theme differs from their wording's, each with its reason | hand, after the check below |

## Cross-week themes

A theme is a subject that recurs across survey weeks — prices, the war, relations with the
West — so one subject can be followed over five years even though FOM words it differently
from year to year ("Военная операция России на Украине" in March 2022, "СВО в целом, успехи
российской армии" in 2025). Each specific event gets exactly one theme, its main subject.
FOM's catch-all rows and the non-response line get none. Each area of news has an "__other"
theme for subjects that do not form a theme of their own.

### How the labels were made (2026-10-15)

1. **Theme list.** Three Claude agents (claude-opus-5-5) each proposed a list from the 1,024
   distinct event wordings (2,772 event-weeks, 2020-W02 to 2025-W11), each from a different
   angle: FOM's own recurring rubrics, what media coverage can be compared on, and a
   hierarchy a first-time reader understands. A fourth agent merged them into
   `configs/fom_theme_taxonomy.json`: definitions, boundary rules, the families of wording
   variants FOM used for one subject, and the wordings whose meaning changes over time.
2. **Labels.** OpenAI Codex (`codex-cli 0.160.0`, model `gpt-6.1-sol`, reasoning effort
   `medium`, second account) gave every wording a theme, 50 wordings per call, 21 calls, all
   on one model. The prompt is the `PROMPT` text in `scripts/fom_themes.py` plus the taxonomy
   and the wordings with their weeks and respondent quotes. Each run's prompts, answers, logs
   and model are kept in `data/interim/themes/labels/<run>/` (not in git), and each seed row
   records the date and model that labelled it.
3. **Check and fixes.** Nine separate agents re-read every label and hunted for subjects
   split across periods; two of them tried to refute every reported problem. No label broke
   the written rules, but four rules were wrong and some generic FOM rubrics change subject
   from week to week. The rules were fixed, Codex relabelled all 1,024 wordings (the two runs
   agree on every wording whose rule did not change), and five survey rows got a week-level
   override. Result: 97.5% of the 2,772 survey events share a theme with a *different*
   wording from another year, against 34.9% that a plain name match links.
   Full write-up: `reports/theme_assembly_check_2026-10-15.md`.

### Adding new survey weeks

New FOM weeks mostly reuse wordings already in `fom_event_themes.csv`: in each year from
2023 to 2025, 68–74% of the events used a wording that had appeared in an earlier week
(58–61% in 2020–2022), so they are labelled the moment the seed is joined. For the rest:

```sh
.venv/bin/python scripts/fom_themes.py prepare
.venv/bin/python scripts/fom_themes.py prompts --new-only
zsh scripts/run_theme_labelling.sh
.venv/bin/python scripts/fom_themes.py seeds
```

Until that is done, an unlabelled event shows without a theme, and dbt warns
(`every_specific_event_has_a_theme`).
