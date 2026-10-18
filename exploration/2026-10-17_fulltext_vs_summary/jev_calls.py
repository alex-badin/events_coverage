#!/usr/bin/env python
"""Paid step: TypeSafe Jev 1.13 via OpenRouter in place of Cohere rerank, on the labelled posts.

One System One request per post: the cleaned full text as `state`, one `noul` question
"does this post report on the event" with the same yes/no rules the Codex labelling prompt
used (run.PROMPT). Jev returns the probability of yes; jev_report.py compares it with the
Codex labels and with Cohere full-text rerank. Writes
data/interim/fulltext_vs_summary/jev_<slug>.json. Skips events already written; stops when
the spend OpenRouter reports passes COST_CAP_USD. `--limit N` scores only N posts per event.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rerank_eval as E  # noqa: E402
import run as R  # noqa: E402
from events_coverage import matching as M  # noqa: E402

MODEL = "typesafe/jev-1.13"
URL = "https://openrouter.ai/api/v1/systemone"
COST_CAP_USD = 0.50
PRICE_PER_M = 0.042


def question(slug):
    m = R.manifest(slug)["event"]
    window = json.loads((R.OUT / f"scores_{slug}.json").read_text())["window"]
    return {"type": "noul",
            "instructions": {
                "event": m["name"],
                "how_respondents_described_it": m["quotes"],
                "survey_week": f"{m['year']}-W{m['week']:02d}",
                "search_window": f"{window[0]} — {window[1]}",
                "question": "Does the news post in the state report on or discuss `event` "
                            "(the event itself, its course, reactions to it, its direct consequences)? "
                            "Judge by the text of the post."},
            "criteria": {
                "true": "The post reports on or discusses this event.",
                "false": "The post is about something else, including a similar event of the same kind "
                         "(another disaster, other negotiations, other prices), or mentions the topic "
                         "only in passing."}}


def ask(key, q, text):
    body = {"model": MODEL, "state": text, "questions": {"on_event": q}}
    for attempt in range(5):
        try:
            r = requests.post(URL, timeout=120, json=body, headers={"Authorization": f"Bearer {key}"})
            if r.ok:
                d = r.json()
                return d["answers"]["on_event"]["noul"], d.get("usage", {})
        except requests.RequestException:
            pass
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{r.status_code} {r.text[:300]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    posts, labels = R.load_posts(), R.load_labels()
    key = M.get_openrouter_key()
    spent = sum(json.loads(p.read_text())["cost_usd"] for p in R.OUT.glob("jev_*.json"))
    for slug in R.EVENTS:
        target = R.OUT / f"jev_{slug}.json"
        if target.exists():
            continue
        if spent > COST_CAP_USD:
            raise SystemExit(f"stopping: ${spent:.3f} spent")
        ids = sorted(E.event_set(slug, posts, labels))[:args.limit]
        q = question(slug)
        with ThreadPoolExecutor(12) as pool:
            res = list(pool.map(lambda i: ask(key, q, posts[i]["text"][:2500]), ids))
        tokens = sum(u.get("input_tokens", 0) for _, u in res)
        cost = sum(u.get("cost", 0) for _, u in res) or tokens * PRICE_PER_M / 1e6
        target.write_text(json.dumps({
            "slug": slug, "model": MODEL, "date": time.strftime("%Y-%m-%d"), "question": q,
            "noul": {str(i): round(float(p), 4) for i, (p, _) in zip(ids, res)},
            "input_tokens": tokens, "cost_usd": cost}, ensure_ascii=False))
        spent += cost
        print(f"{slug}: {len(ids)} posts, {tokens} tokens, ${cost:.4f}; total ${spent:.4f}", flush=True)


if __name__ == "__main__":
    main()
