#!/usr/bin/env python3
"""Give every FOM survey event a cross-week theme.

A theme is a subject that recurs across survey weeks (prices, the war, Russia–US relations),
so one subject can be followed over time even though FOM words it differently from year to
year. The theme list lives in configs/fom_theme_taxonomy.json; this script turns it and the
model labels into the two dbt seeds the warehouse reads.

Run from the repository root, after `dbt build` (prepare reads stg_events):

    .venv/bin/python scripts/fom_themes.py prepare              # distinct wordings -> data/interim/themes/
    .venv/bin/python scripts/fom_themes.py prompts --new-only   # a new labelling run, 50 wordings per prompt
    zsh scripts/run_theme_labelling.sh                          # Codex answers each prompt of that run
    .venv/bin/python scripts/fom_themes.py seeds                # answers -> dbt/seeds/fom_themes.csv, fom_event_themes.csv

Labels are keyed by the wording itself (a hash of its normalised text), never by its
position in a list, so a change to earlier survey data cannot hand one wording another's
theme. Every `prompts` call starts a new run folder under data/interim/themes/labels/, and
`seeds` reads the answers of every run in date order, so earlier runs stay on disk as the
record of what was asked and answered. Without --new-only, `prompts` asks for every wording.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_DB = PROJECT_ROOT / "data" / "warehouse" / "events.duckdb"
TAXONOMY = PROJECT_ROOT / "configs" / "fom_theme_taxonomy.json"
WORK = PROJECT_ROOT / "data" / "interim" / "themes"
RUNS = WORK / "labels"
SEED_THEMES = PROJECT_ROOT / "dbt" / "seeds" / "fom_themes.csv"
SEED_EVENT_THEMES = PROJECT_ROOT / "dbt" / "seeds" / "fom_event_themes.csv"
SLICE = 50

# The shape Codex must answer in (passed to `codex exec --output-schema`).
LABEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"labels": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string"},
            "theme_id": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["key", "theme_id", "note"],
    }}},
    "required": ["labels"],
}


def normalise(name: str) -> str:
    """The form that treats two spellings of one FOM wording as the same wording."""
    text = name.lower().replace("ё", "е")
    text = re.sub(r"[«»\"“”„.,:;!?()\-–—]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def key_of(name: str) -> str:
    """A stable id for a wording: the same text always gets the same key."""
    return "k" + hashlib.sha1(normalise(name).encode("utf-8")).hexdigest()[:10]


def quotes_of(text) -> list[str]:
    try:
        return [str(q).strip().strip("«»") for q in ast.literal_eval(text or "[]")]
    except (ValueError, SyntaxError):
        return []


def prepare() -> None:
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    events = con.sql(
        """
        select fom_year, fom_week, week_start, event_name, quote_examples, attention_percentage
        from stg_events
        where event_kind = 'specific event'
        """
    ).df()
    con.close()

    events["key"] = events.event_name.map(key_of)
    events["wk"] = events.apply(lambda r: f"{r.fom_year}-W{r.fom_week:02d}", axis=1)
    rows = []
    for key, g in sorted(events.groupby("key"), key=lambda kv: (kv[1].week_start.min(), kv[0])):
        g = g.sort_values("week_start")
        quotes = []
        for text in g.quote_examples:
            quotes += [q for q in quotes_of(text) if q not in quotes]
        rows.append({
            "key": key,
            "name": g.event_name.value_counts().index[0],
            "n_weeks": g.wk.nunique(),
            "first_week": g.wk.iloc[0],
            "last_week": g.wk.iloc[-1],
            "weeks": " ".join(g.wk.unique()),
            "peak_pct": g.attention_percentage.max(),
            "quotes": " | ".join(quotes[:3]),
            "spellings": " || ".join(sorted(g.event_name.unique())),
        })
    names = pd.DataFrame(rows)
    WORK.mkdir(parents=True, exist_ok=True)
    names.to_csv(WORK / "fom_event_names.csv", index=False)

    events["quotes"] = events.quote_examples.map(lambda t: " | ".join(quotes_of(t)))
    events.sort_values(["week_start", "attention_percentage"], ascending=[True, False])[
        ["wk", "key", "event_name", "attention_percentage", "quotes"]
    ].to_csv(WORK / "fom_event_weeks_quotes.csv", index=False)
    print(f"{len(events):,} event-weeks, {len(names):,} distinct wordings -> {WORK.relative_to(PROJECT_ROOT)}")


PROMPT = """You assign a theme to each event wording from the FOM weekly survey (Фонд «Общественное мнение»:
each week respondents name the events of the past week they remember; FOM publishes the list).

Below are the theme taxonomy (definitions and boundary notes are the labelling rules) and a list of
event wordings. For EVERY key in the list return exactly one theme_id from the taxonomy.
- Use the respondent quotes to understand vague wordings.
- Use the weeks to tell the period: the same words can mean different things in different years
  (for example "События на Украине" in 2020-2021 vs 2022 onwards).
- If no specific theme fits, use the umbrella's catch-all theme ("<umbrella_id>__other").
- note: a short phrase when the choice was hard; empty otherwise.
Everything you need is in this message; do not run commands or read files.

TAXONOMY:
{taxonomy}

WORDINGS (key | wording | weeks: first..last, number of weeks | up to 3 respondent quotes):
{rows}
"""


def labelled_keys() -> set[str]:
    if not SEED_EVENT_THEMES.is_file():
        return set()
    return {key_of(r["event_name"]) for r in csv.DictReader(SEED_EVENT_THEMES.open(encoding="utf-8"))}


def prompts(new_only: bool) -> None:
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    names = pd.read_csv(WORK / "fom_event_names.csv")
    if new_only:
        names = names[~names.key.isin(labelled_keys())]
    if names.empty:
        print("Every wording already has a theme; no run created.")
        return
    rules = json.dumps(
        {"umbrellas": taxonomy["umbrellas"],
         "themes": [{k: t[k] for k in ("theme_id", "umbrella_id", "label_en", "definition", "boundary_notes")}
                    for t in taxonomy["themes"]]},
        ensure_ascii=False, indent=1)
    run = RUNS / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    (run / "prompts").mkdir(parents=True)
    (run / "schema.json").write_text(json.dumps(LABEL_SCHEMA, indent=1), encoding="utf-8")
    for start in range(0, len(names), SLICE):
        part = names.iloc[start:start + SLICE]
        rows = "\n".join(
            f"{r.key} | {r['name']} | {r.first_week}..{r.last_week}, {r.n_weeks} | "
            f"{r.quotes if isinstance(r.quotes, str) else ''}"
            for _, r in part.iterrows())
        (run / "prompts" / f"slice_{start // SLICE + 1:02d}.txt").write_text(
            PROMPT.format(taxonomy=rules, rows=rows), encoding="utf-8")
    print(f"{len(names):,} wordings -> {len(list((run / 'prompts').glob('*.txt')))} prompts in "
          f"{run.relative_to(PROJECT_ROOT)}")


def label_runs() -> list[Path]:
    """Labelling run folders, oldest first (their names start with the date and time)."""
    return sorted(p for p in RUNS.glob("*") if (p / "prompts").is_dir())


def run_answers() -> tuple[dict[str, dict], dict[Path, int]]:
    """Every valid answer of every run, later runs overriding earlier ones, keyed by wording.

    Also returns, per run, how many of its prompts are still without a valid answer.
    """
    answers, incomplete = {}, {}
    for run in label_runs():
        run_model = run / "model.txt"   # older runs recorded one model for the whole run
        unanswered = 0
        for prompt_path in sorted((run / "prompts").glob("slice_*.txt")):
            path = run / "out" / f"{prompt_path.stem}.json"
            try:
                labels = json.loads(path.read_text(encoding="utf-8"))["labels"]
            except (OSError, ValueError, KeyError, TypeError):
                unanswered += 1
                continue
            model_path = path.with_suffix(".model")
            model = next((f.read_text(encoding="utf-8").strip() for f in (model_path, run_model) if f.is_file()),
                         "unknown")
            asked = set(re.findall(r"^(k[0-9a-f]{10}) \|", prompt_path.read_text(encoding="utf-8"), flags=re.M))
            for item in labels:
                # Only answers to a key that this exact prompt asked about count.
                if item.get("key") in asked:
                    answers[item["key"]] = {"theme_id": item["theme_id"],
                                            "labelled_on": run.name[:10], "labelled_by": model}
        if unanswered:
            incomplete[run] = unanswered
    return answers, incomplete


def seeds(allow_incomplete: bool) -> None:
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    umbrellas = {u["umbrella_id"]: (i + 1, u) for i, u in enumerate(taxonomy["umbrellas"])}
    theme_ids = set()
    theme_rows = []
    for i, t in enumerate(taxonomy["themes"]):
        order, umbrella = umbrellas[t["umbrella_id"]]
        theme_ids.add(t["theme_id"])
        theme_rows.append({
            "theme_id": t["theme_id"],
            "theme_label": t["label_en"],
            "label_ru": t["label_ru"],
            "umbrella_id": t["umbrella_id"],
            "umbrella_label": umbrella["label_en"],
            "umbrella_order": order,
            "theme_order": i + 1,
            "is_other_theme": t["theme_id"].endswith("__other"),
            "definition": t["definition"],
        })

    # What is already labelled, by wording key: the seed first, then every run's answers.
    by_key = {}
    if SEED_EVENT_THEMES.is_file():
        for r in csv.DictReader(SEED_EVENT_THEMES.open(encoding="utf-8")):
            by_key[key_of(r["event_name"])] = {k: r[k] for k in ("theme_id", "labelled_on", "labelled_by")}
    answers, incomplete = run_answers()
    newest = label_runs()[-1] if label_runs() else None
    if newest in incomplete and not allow_incomplete:
        sys.exit(f"The newest labelling run, {newest.relative_to(PROJECT_ROOT)}, has {incomplete[newest]} "
                 "prompts without a valid answer. Rerun scripts/run_theme_labelling.sh, or pass "
                 "--allow-incomplete to keep older labels for those wordings. Nothing was written.")
    by_key.update(answers)

    # One row per exact spelling in the current survey data, so the warehouse joins on the
    # name as FOM printed it. A new spelling of a known wording takes that wording's theme.
    names = pd.read_csv(WORK / "fom_event_names.csv")
    rows, missing = [], []
    for _, n in names.iterrows():
        label = by_key.get(n.key)
        for spelling in n.spellings.split(" || "):
            if label:
                rows.append({"event_name": spelling, **label})
            else:
                missing.append(spelling)

    # Check before writing anything, so the two seeds can never disagree with each other.
    # Only labels that will be written count: an old answer for a wording that has left the
    # data cannot block a run.
    unknown = sorted({r["theme_id"] for r in rows} - theme_ids)
    if unknown:
        users = sorted({r["event_name"] for r in rows if r["theme_id"] in unknown})
        sys.exit(f"Labels use theme ids that are not in the taxonomy: {unknown}, e.g. {users[:3]}. "
                 "Relabel those wordings or restore the themes. Nothing was written.")
    pd.DataFrame(theme_rows).to_csv(SEED_THEMES, index=False)
    pd.DataFrame(sorted(rows, key=lambda r: r["event_name"])).to_csv(SEED_EVENT_THEMES, index=False)
    print(f"{len(theme_rows)} themes -> {SEED_THEMES.relative_to(PROJECT_ROOT)}")
    print(f"{len(rows):,} spellings -> {SEED_EVENT_THEMES.relative_to(PROJECT_ROOT)}")
    for run, count in incomplete.items():
        print(f"note: {run.relative_to(PROJECT_ROOT)} has {count} prompts without a valid answer")
    if missing:
        sys.exit(f"{len(missing)} spellings have no theme yet, e.g. {missing[:3]}. "
                 "Run `prompts --new-only` and the labelling script, then `seeds` again.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["prepare", "prompts", "seeds"])
    parser.add_argument("--new-only", action="store_true", help="prompts: only wordings without a theme yet")
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="seeds: accept a newest run with unanswered prompts (older labels stay for those)")
    args = parser.parse_args()
    if args.step == "prepare":
        prepare()
    elif args.step == "prompts":
        prompts(args.new_only)
    else:
        seeds(args.allow_incomplete)


if __name__ == "__main__":
    main()
