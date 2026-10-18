"""Shared, free parts of the Jev selection experiment: events, candidates, questions, labels.

Dev events: the five already labelled by Codex in ../2026-10-17_fulltext_vs_summary/.
Hold-out events: three more FOM events from the same full-text window (14.02-26.03.2025),
nothing is tuned on them. Posts, cleaned full text and fragment vectors are reused from
data/interim/fulltext_vs_summary/.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FT = HERE.parent / "2026-10-17_fulltext_vs_summary"
sys.path.insert(0, str(FT))
sys.path.insert(0, str(ROOT / "src"))
import run as R  # noqa: E402
import rerank_eval as E  # noqa: E402

OUT = ROOT / "data" / "interim" / "jev_selection"
OUT.mkdir(parents=True, exist_ok=True)
TOP_K = 3000              # cosine candidates per hold-out event, as the old pipeline cap
POST_CHARS = 2500         # what Codex and Jev see of each post

DEV = R.EVENTS
HOLDOUT = {
    "drones_moscow_2025w11": {
        "name": "Обстрелы российских территорий, атака беспилотников на Москву", "year": 2025, "week": 11,
        "quotes": ["«Дроны по всей России»", "«воздушная тревога»", "«дроны летали по улицам деревни»",
                   "«прилетели беспилотники в количестве 337 штук»", "«дроны ВСУ, отправленные на Москву»",
                   "«дроны прилетели в Домодедово»", "«налёт массированный на Москву БПЛА»"]},
    "putin_lukashenko_2025w11": {
        "name": "Встреча В. Путина и А. Лукашенко", "year": 2025, "week": 11,
        "quotes": ["«Встреча Путина и Лукашенко»",
                   "«президент Белоруссии Лукашенко приехал в Россию – с Путиным встречался»"]},
    "trump_statements_2025w10": {
        "name": "Высказывания и действия Д. Трампа", "year": 2025, "week": 10,
        "quotes": ["«Высказывания президента Трампа обо всём. Он довольно часто высказывается на разные темы»",
                   "«выступление Трампа в Конгрессе»", "«пресс-конференция Трампа в США»", "«действия Трампа»",
                   "«Трамп сделал закон о запрете гендеров»"]},
}
EVENTS = list(DEV) + list(HOLDOUT)


def event(slug):
    """name, quotes, survey week and search window, same rule as the pipeline manifests:
    3 days before the ISO week's Monday to 10 days after its Sunday."""
    if slug in HOLDOUT:
        e = HOLDOUT[slug]
        monday = date.fromisocalendar(e["year"], e["week"], 1)
        lo, hi = monday - timedelta(days=3), monday + timedelta(days=6 + 10 + 1)
        return {"name": e["name"], "quotes": e["quotes"], "week": f"{e['year']}-W{e['week']:02d}",
                "window": [lo.isoformat(), hi.isoformat()]}
    m = R.manifest(slug)["event"]
    s = json.loads((R.OUT / f"scores_{slug}.json").read_text())
    return {"name": m["name"], "quotes": m["quotes"], "week": f"{m['year']}-W{m['week']:02d}",
            "window": s["window"]}


def scores_path(slug):
    return (R.OUT if slug in DEV else OUT) / f"scores_{slug}.json"


def ranked_candidates(slug, k=TOP_K):
    """Posts of the window by full-text cosine, best first."""
    rows = json.loads(scores_path(slug).read_text())["rows"]
    return [r["i"] for r in sorted(rows, key=lambda r: -r["fulltext"])][:k]


def dev_posts(slug, posts, labels):
    return sorted(E.event_set(slug, posts, labels))


def brief(slug):
    p = OUT / "briefs" / "out" / f"{slug}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ------------------------------------------------------------------------------ questions
def _event_block(slug, with_brief):
    e = event(slug)
    block = {"event": e["name"], "how_respondents_described_it": e["quotes"],
             "survey_week": e["week"], "search_window": f"{e['window'][0]} — {e['window'][1]}"}
    if with_brief:
        b = brief(slug)
        block.update({"what_happened": b["what_happened"], "counts_as_coverage": b["counts"],
                      "does_not_count": b["does_not_count"]})
    return block


GRADES = {
    "event_itself": "The post reports on the event itself: what happened, its course, details, participants.",
    "reaction_or_consequence": "The post is about a reaction to the event, its direct consequences, "
                               "its preparation or follow-up, or discusses the event as part of a wider story.",
    "same_topic_other_event": "The post is on the same topic but about a different event or development "
                              "(another meeting, another attack, other prices), or mentions the event only in passing.",
    "unrelated": "The post is about something else.",
}
ON_EVENT = ("event_itself", "reaction_or_consequence")


def question(slug, variant):
    """v0  noul, event name and quotes (the first test)
       v1  choice over four grades, event name and quotes
       v2  choice over four grades, plus the event brief
       v3  noul, plus the event brief"""
    with_brief = variant in ("v2", "v3")
    block = _event_block(slug, with_brief)
    if variant in ("v1", "v2"):
        block["question"] = "How does the news post in the state relate to `event`? Judge by the text of the post."
        return {"type": "choice", "instructions": block, "criteria": GRADES}
    block["question"] = ("Does the news post in the state report on or discuss `event` (the event itself, "
                         "its course, reactions to it, its direct consequences)? Judge by the text of the post.")
    return {"type": "noul", "instructions": block,
            "criteria": {"true": "The post reports on or discusses this event.",
                         "false": "The post is about something else, including a similar event of the same kind "
                                  "(another disaster, other negotiations, other prices), or mentions the topic "
                                  "only in passing."}}


def p_on_event(answer):
    """Probability the post is on the event, from a noul or a choice answer."""
    if answer["type"] == "noul":
        return answer["noul"]
    probs = answer.get("probabilities") or {}
    return sum(probs.get(k, 0.0) for k in ON_EVENT)


def jev_scores(slug, variant):
    p = OUT / "jev" / variant / f"{slug}.json"
    if not p.exists():
        return None
    return {int(k): v for k, v in json.loads(p.read_text())["p"].items()}
