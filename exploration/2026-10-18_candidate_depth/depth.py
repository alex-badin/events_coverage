#!/usr/bin/env python
"""How deep the candidate list has to go: places 3,001-6,000 for the two hold-out events whose
on-event share was still high at place 3,000 on 2026-10-17 (drones over Moscow, Trump's
statements). Reuses that experiment's posts, fragment vectors, event briefs and Jev question.

  jev       paid: Jev 1.13 v3 on places 3,001-6,000 (OpenRouter); each answer is saved as it
            arrives, the step stops at CAP_USD (owner's budget for this test: $1)
  prompts   free: 150 random posts from each of two bands (3,001-4,500, 4,501-6,000) for Codex
  collect   free: Codex answers -> labels/<slug>.json
  report    free: on-event share by place band 1-6,000, and stop rules on the longer list

Codex: zsh ../2026-10-17_jev_selection/codex_answer.sh data/interim/candidate_depth/labelling
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-17_jev_selection"))
import calls as K  # noqa: E402
import common as C  # noqa: E402
from events_coverage import matching as M  # noqa: E402

OUT = C.ROOT / "data" / "interim" / "candidate_depth"
LEDGER = OUT / "spend.jsonl"
CAP_USD = 0.90
EVENTS = ["drones_moscow_2025w11", "trump_statements_2025w10"]
DEPTH = 6000
NEW_BANDS = [(3000, 4500), (4500, 6000)]
PER_BAND = 150
OLD_BANDS = [(0, 150), (150, 500), (500, 1000), (1000, 2000), (2000, 3000)]
LAB = OUT / "labelling"


def spent():
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in LEDGER.read_text().splitlines() if l.strip())


def jev():
    OUT.mkdir(parents=True, exist_ok=True)
    posts = K.R_posts()
    key = M.get_openrouter_key()
    for slug in EVENTS:
        target = OUT / f"jev_{slug}.jsonl"          # one line per answered post
        done = set()
        if target.exists():
            done = {json.loads(l)["i"] for l in target.read_text().splitlines() if l.strip()}
        ids = [i for i in C.ranked_candidates(slug, DEPTH)[3000:] if i not in done]
        questions = {"v3": C.question(slug, "v3")}
        print(f"{slug}: {len(ids)} posts to score", flush=True)
        for k in range(0, len(ids), 300):
            if spent() > CAP_USD:
                raise SystemExit(f"stopping: ${spent():.3f} spent of the ${CAP_USD} cap")
            chunk = ids[k:k + 300]
            with ThreadPoolExecutor(12) as pool, target.open("a") as f:
                futures = [(i, pool.submit(K.ask_jev, key, questions, posts[i]["text"][:C.POST_CHARS]))
                           for i in chunk]
                tokens = cost = 0.0
                for i, fut in futures:
                    try:
                        answers, usage = fut.result()
                    except RuntimeError as e:
                        print(f"  {i}: {e}", flush=True)
                        continue
                    t = usage.get("input_tokens", 0)
                    c = usage.get("cost", 0) or t * K.JEV_PRICE_PER_M / 1e6
                    tokens += t; cost += c
                    f.write(json.dumps({"i": i, "p": round(float(C.p_on_event(answers["v3"])), 4),
                                        "input_tokens": t, "usd": c}) + "\n")
                    f.flush()
            with LEDGER.open("a") as g:
                g.write(json.dumps({"step": "jev", "slug": slug, "posts": len(chunk), "input_tokens": tokens,
                                    "usd": round(cost, 5), "date": time.strftime("%Y-%m-%d %H:%M")}) + "\n")
            print(f"  {k + len(chunk)} done, ${cost:.4f}; ledger ${spent():.3f}", flush=True)


def sample(slug):
    ranked = C.ranked_candidates(slug, DEPTH)
    rng = np.random.default_rng(18)
    picked, weight = [], {}
    for lo, hi in NEW_BANDS:
        band = ranked[lo:hi]
        for t in rng.choice(len(band), size=PER_BAND, replace=False):
            picked.append(band[t]); weight[band[t]] = len(band) / PER_BAND
    return picked, weight


def prompts():
    posts = K.R_posts()
    (LAB / "prompts").mkdir(parents=True, exist_ok=True)
    (LAB / "schema.json").write_text((C.R.OUT / "labels" / "schema.json").read_text())
    for slug in EVENTS:
        e = C.event(slug)
        ids, _ = sample(slug)
        ids = [int(i) for i in np.random.default_rng(6).permutation(ids)]
        for k in range(0, len(ids), C.R.SLICE):
            block = "\n\n".join(f"[id {i}] {posts[i]['text'][:C.POST_CHARS]}" for i in ids[k:k + C.R.SLICE])
            text = C.R.PROMPT.format(week=e["week"], name=e["name"], quotes="; ".join(e["quotes"]),
                                     lo=e["window"][0], hi=e["window"][1], posts=block)
            (LAB / "prompts" / f"{slug}_{k // C.R.SLICE:03d}.txt").write_text(text, encoding="utf-8")
        print(f"{slug}: {len(ids)} posts")


def collect():
    (OUT / "labels").mkdir(exist_ok=True)
    for slug in EVENTS:
        ids, weight = sample(slug)
        labels = {}
        for p in sorted((LAB / "out").glob(f"{slug}_*.json")):
            for item in json.loads(p.read_text())["labels"]:
                labels[int(item["id"])] = item["label"] == "yes"
        missing = [i for i in ids if i not in labels]
        if missing:
            raise SystemExit(f"{slug}: {len(missing)} unlabelled; rerun codex_answer.sh")
        (OUT / "labels" / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "labeller": "gpt-6.1-sol via codex exec, reasoning medium", "bands": NEW_BANDS,
            "labels": {str(i): labels[i] for i in ids}, "weights": {str(i): weight[i] for i in ids}}))
        print(f"{slug}: {sum(labels[i] for i in ids)} of {len(ids)} on-event")


def report():
    result = {}
    for slug in EVENTS:
        ranked = C.ranked_candidates(slug, DEPTH)
        rank = {i: r for r, i in enumerate(ranked)}
        p = dict(C.jev_scores(slug, "v3"))
        for l in (OUT / f"jev_{slug}.jsonl").read_text().splitlines():
            d = json.loads(l); p[d["i"]] = d["p"]
        old = json.loads((C.OUT / "holdout_labels" / f"{slug}.json").read_text())
        new = json.loads((OUT / "labels" / f"{slug}.json").read_text())
        truth = {int(k): v for d in (old, new) for k, v in d["labels"].items()}
        w = {int(k): v for d in (old, new) for k, v in d["weights"].items()}
        bands = []
        for lo, hi in OLD_BANDS + NEW_BANDS:
            ids = [i for i in truth if lo <= rank[i] < hi]
            scored = [i for i in ranked[lo:hi] if i in p]
            bands.append({"places": f"{lo + 1}-{hi}", "codex_on_event": round(sum(truth[i] for i in ids) / len(ids), 3),
                          "on_event_est": round(sum(w[i] for i in ids if truth[i])),
                          "jev_yes_share": round(sum(p[i] >= 0.5 for i in scored) / max(1, len(scored)), 3)})
        on6000 = sum(w[i] for i in truth if truth[i])
        rules = []
        for B in (250, 500):
            for share in (0.05, 0.10, 0.20):
                depth = 0
                while depth < DEPTH:
                    batch = [i for i in ranked[depth:depth + B] if i in p]
                    depth += B
                    if sum(p[i] >= 0.5 for i in batch) / max(1, len(batch)) < share:
                        break
                got = sum(w[i] for i in truth if truth[i] and rank[i] < depth)
                rules.append({"batch": B, "stop_below": share, "scored": min(depth, DEPTH),
                              "share_of_on_event_in_6000": round(got / on6000, 3)})
        result[slug] = {"on_event_in_6000_est": round(on6000), "bands": bands, "rules": rules}
    (Path(__file__).parent / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    {"jev": jev, "prompts": prompts, "collect": collect, "report": report}[sys.argv[1]]()
