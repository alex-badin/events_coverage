"""Shared, free parts of the ten-event test: events, posts, candidates, Jev question, labels, spend.

The three hold-out events of ../2026-10-17_jev_selection/ keep their data there (posts of the
14.02-26.03.2025 window, Jev v3, Codex labels, DeepSeek labels). The seven new events get their
own window posts, cleaned and embedded the same way, under data/interim/ten_events_readers/<slug>/.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JS = HERE.parent / "2026-10-17_jev_selection"
sys.path.insert(0, str(JS))
import common as C  # noqa: E402  (also puts run.py and src/ on the path)

R = C.R
OUT = ROOT / "data" / "interim" / "ten_events_readers"
OUT.mkdir(parents=True, exist_ok=True)
TOP_K = C.TOP_K            # 3,000 cosine candidates per event
POST_CHARS = C.POST_CHARS  # 2,500 characters of each post for Jev, Codex and readers

# Seven new events: four from 2020-2022, three from 2023-2025, different topics; names and
# quotes as in stg_events (the FOM table).
NEW = {
    "mishustin_government_2020w03": {
        "name": "Отставка правительства, назначение М. Мишустина новым премьер-министром", "year": 2020, "week": 3,
        "quotes": ["Кабинет министров убрали", "неожиданная смена премьер-министра",
                   "отставка правительства, слава тебе, господи!", "утверждение премьер-министра сегодня в Думе",
                   "избрание Мишустина", "Медведева перевели – жаль, что не выкинули совсем"]},
    "karabakh_ceasefire_2020w46": {
        "name": "Прекращение армяно-азербайджанского вооруженного конфликта, ввод российских миротворцев",
        "year": 2020, "week": 46,
        "quotes": ["«Армения, карабахский результат, определились с этим делом»",
                   "«заключили мирное соглашение на Карабахе»", "«остановка войны в Нагорном Карабахе»",
                   "«Россия мирный коридор создает в Азербайджане и Армении»",
                   "«введение миротворческих сил в Нагорном Карабахе»"]},
    "kazan_school_2021w19": {
        "name": "Массовое убийство школьников в казанской школе", "year": 2021, "week": 19,
        "quotes": ["«Трагедия в Казани, очень сильно переживали»", "«детей убили в Казани»",
                   "«вооруженное нападение в Казани»", "«Татария, жертвы»", "«трагедия в гимназии №175»"]},
    "beijing_olympics_2022w07": {
        "name": "Зимние Олимпийские игры в Китае", "year": 2022, "week": 7,
        "quotes": ["«Олимпиада в Китае»", "«Олимпиада в Пекине продолжается, российские спортсмены хорошо выступают»",
                   "«наши взяли золото в лыжах»", "«Олимпиада, Валиева, загнобили девчонку»"]},
    "turkey_earthquake_2023w06": {
        "name": "Землетрясение в Турции и Сирии", "year": 2023, "week": 6,
        "quotes": ["«Трагедия в Турции и Сирии»", "«в Турции и Сирии землетрясение»",
                   "«в Турции беда: землетрясение»", "«землетрясение, людей жалко»",
                   "«землетрясение в Турции, много погибших»", "«события в Турции, Сирии, спасение детей»"]},
    "prigozhin_mutiny_2023w26": {
        "name": "Мятеж, организованный Е. Пригожиным, события вокруг ЧВК «Вагнер»", "year": 2023, "week": 26,
        "quotes": ["«23-24-го Евгений Пригожин хотел свергнуть правительство»", "«попытка свержения нашего правительства»",
                   "«бунт Пригожина»", "«вагнеровцы -полумятеж»", "«марш справедливости Пригожина»",
                   "«шел за справедливостью Пригожин»",
                   "«переживали за Путина из-за наступления на Москву военного Пригожина»", "«введение КТО»",
                   "«перекопанные дороги в Липецкой области, закрытие трасс»",
                   "«с участием Белоруссии договорились с Пригожиным»"]},
    "crocus_attack_2024w13": {
        "name": "Теракт в «Крокус Сити Холле»", "year": 2024, "week": 13,
        "quotes": ["«Крокус Сити Холл»", "«теракт 22 марта»", "«теракт в Подмосковье, в Красногорске»",
                   "«теракт, конечно. Это главное событие, и все его обсуждали»", "«теракт ужасный»",
                   "«расследование теракта»", "«террористов показывали»"]},
}
OLD = list(C.HOLDOUT)
EVENTS = list(NEW) + OLD
SHORT = {
    "mishustin_government_2020w03": "Отставка правительства, Мишустин, 2020-W03",
    "karabakh_ceasefire_2020w46": "Прекращение войны в Карабахе, 2020-W46",
    "kazan_school_2021w19": "Убийство школьников в Казани, 2021-W19",
    "beijing_olympics_2022w07": "Олимпиада в Пекине, 2022-W07",
    "turkey_earthquake_2023w06": "Землетрясение в Турции и Сирии, 2023-W06",
    "prigozhin_mutiny_2023w26": "Мятеж Пригожина, 2023-W26",
    "crocus_attack_2024w13": "Теракт в «Крокусе», 2024-W13",
    "drones_moscow_2025w11": "Атака беспилотников на Москву, 2025-W11",
    "putin_lukashenko_2025w11": "Встреча Путина и Лукашенко, 2025-W11",
    "trump_statements_2025w10": "Высказывания и действия Трампа, 2025-W10",
}


def era(slug):
    return "2020–2022" if int(slug.rsplit("_", 1)[1][:4]) <= 2022 else "2023–2025"


def event(slug):
    """Name, quotes, survey week and search window: 3 days before the ISO week's Monday to
    10 days after its Sunday, as in the pipeline manifests."""
    if slug in OLD:
        return C.event(slug)
    e = NEW[slug]
    monday = date.fromisocalendar(e["year"], e["week"], 1)
    lo, hi = monday - timedelta(days=3), monday + timedelta(days=6 + 10 + 1)
    return {"name": e["name"], "quotes": e["quotes"], "week": f"{e['year']}-W{e['week']:02d}",
            "window": [lo.isoformat(), hi.isoformat()]}


def folder(slug):
    return OUT / slug


@lru_cache(maxsize=None)
def posts(slug):
    """Cleaned posts of the event's window; candidate ids index into this list."""
    if slug in OLD:
        return R.load_posts()
    with (folder(slug) / "texts.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def scores_path(slug):
    return C.scores_path(slug) if slug in OLD else folder(slug) / "scores.json"


def ranked(slug, k=TOP_K):
    rows = json.loads(scores_path(slug).read_text())["rows"]
    return [r["i"] for r in sorted(rows, key=lambda r: -r["fulltext"])][:k]


def brief(slug):
    if slug in OLD:
        return C.brief(slug)
    p = OUT / "briefs" / "out" / f"{slug}.json"
    return json.loads(p.read_text()) if p.exists() else None


def question(slug):
    """Jev v3 (yes/no plus the event brief), built by the jev_selection code itself so the text is
    identical to the earlier runs."""
    saved = C.event, C.brief
    C.event, C.brief = event, brief
    try:
        return C.question(slug, "v3")
    finally:
        C.event, C.brief = saved


def jev(slug):
    if slug in OLD:
        return C.jev_scores(slug, "v3")
    p = OUT / "jev" / f"{slug}.json"
    return {int(k): v for k, v in json.loads(p.read_text())["p"].items()} if p.exists() else None


def labels(slug):
    """Codex reference labels and band weights of the 750 sampled candidates."""
    base = C.OUT if slug in OLD else OUT
    d = json.loads((base / "holdout_labels" / f"{slug}.json").read_text())
    return ({int(k): v for k, v in d["labels"].items()}, {int(k): v for k, v in d["weights"].items()})


# ----------------------------------------------------------------------------- spend
CAP_USD = 9.50             # the owner's budget for the whole task is $10
LEDGER = OUT / "spend.jsonl"


def spent():
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in LEDGER.read_text().splitlines() if line.strip())


def book(step, usd, **extra):
    with LEDGER.open("a") as f:
        f.write(json.dumps({"step": step, "usd": round(usd, 5), "date": time.strftime("%Y-%m-%d %H:%M"), **extra},
                           ensure_ascii=False) + "\n")


def guard():
    if spent() > CAP_USD:
        raise SystemExit(f"stopping: ${spent():.3f} spent of the ${CAP_USD} cap")
