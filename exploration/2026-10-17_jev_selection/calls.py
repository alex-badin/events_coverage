#!/usr/bin/env python
"""Paid steps of the Jev selection experiment. Every step is resumable and adds its spend to
data/interim/jev_selection/spend.jsonl; a step refuses to start once the ledger passes CAP_USD
(the owner's budget for this experiment is $5).

  cosine    hold-out events: Qwen3 query vectors via OpenRouter, full-text cosine of every
            window post (fragment vectors already on disk)
  jev       TypeSafe Jev 1.13 via OpenRouter, one request per post with every question variant
            of common.question; --set dev (the labelled posts) or holdout (top-3,000 candidates)
  cohere    Cohere rerank-v3.5 on the hold-out candidates' full text, one query per probe,
            best score kept (the pipeline's rule)
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

import common as C
from events_coverage import matching as M

CAP_USD = 4.50
LEDGER = C.OUT / "spend.jsonl"
JEV_URL = "https://openrouter.ai/api/v1/systemone"
JEV_MODEL = "typesafe/jev-1.13"
JEV_PRICE_PER_M = 0.042
VARIANTS = {"dev": ["v1", "v2", "v3"], "holdout": ["v2", "v3"]}  # v1 lost clearly on dev


def spent():
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(l)["usd"] for l in LEDGER.read_text().splitlines() if l.strip())


def book(step, usd, **extra):
    with LEDGER.open("a") as f:
        f.write(json.dumps({"step": step, "usd": round(usd, 5), "date": time.strftime("%Y-%m-%d %H:%M"), **extra},
                           ensure_ascii=False) + "\n")


def guard():
    if spent() > CAP_USD:
        raise SystemExit(f"stopping: ${spent():.3f} spent of the ${CAP_USD} cap")


# ------------------------------------------------------------------------------- cosine
def cosine():
    posts = R_posts()
    owners, X = C.R.fragment_matrix()
    for slug in C.HOLDOUT:
        target = C.scores_path(slug)
        if target.exists():
            continue
        guard()
        e = C.event(slug)
        probes = M.build_probes({"name": e["name"], "quotes": e["quotes"]})
        Q = M.embed_texts_qwen3(probes)
        per_frag = (X.astype(np.float32) @ Q.T).max(axis=1)
        full = np.full(len(posts), -1.0, np.float32)
        np.maximum.at(full, owners, per_frag)
        lo, hi = e["window"]
        rows = [{"i": i, "fulltext": float(full[i])} for i, p in enumerate(posts)
                if lo <= p["date"][:10] < hi and full[i] > -1]
        target.write_text(json.dumps({"slug": slug, "probes": probes, "window": [lo, hi], "rows": rows}))
        book("cosine", 0.0001, slug=slug)
        print(f"{slug}: {len(rows):,} window posts with text, {len(probes)} probes")


_POSTS = None


def R_posts():
    global _POSTS
    if _POSTS is None:
        _POSTS = C.R.load_posts()
    return _POSTS


# ---------------------------------------------------------------------------------- jev
def ask_jev(key, questions, text):
    body = {"model": JEV_MODEL, "state": text, "questions": questions}
    r = None
    for attempt in range(6):
        try:
            r = requests.post(JEV_URL, timeout=120, json=body, headers={"Authorization": f"Bearer {key}"})
            if r.ok:
                d = r.json()
                return d["answers"], d.get("usage", {})
        except requests.RequestException:
            pass
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{getattr(r, 'status_code', '?')} {getattr(r, 'text', '')[:300]}")


def jev(which, limit=None):
    posts = R_posts()
    labels = C.R.load_labels() if which == "dev" else None
    key = M.get_openrouter_key()
    for slug in (C.DEV if which == "dev" else C.HOLDOUT):
        targets = {v: C.OUT / "jev" / v / f"{slug}.json" for v in VARIANTS[which]}
        if all(t.exists() for t in targets.values()):
            continue
        guard()
        ids = C.dev_posts(slug, posts, labels) if which == "dev" else C.ranked_candidates(slug)
        ids = ids[:limit] if limit else ids
        questions = {v: C.question(slug, v) for v in VARIANTS[which]}
        with ThreadPoolExecutor(12) as pool:
            res = list(pool.map(lambda i: ask_jev(key, questions, posts[i]["text"][:C.POST_CHARS]), ids))
        tokens = sum(u.get("input_tokens", 0) for _, u in res)
        cost = sum(u.get("cost", 0) for _, u in res) or tokens * JEV_PRICE_PER_M / 1e6
        for v, t in targets.items():
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(json.dumps({
                "slug": slug, "variant": v, "model": JEV_MODEL, "date": time.strftime("%Y-%m-%d"),
                "question": questions[v],
                "p": {str(i): round(float(C.p_on_event(a[v])), 4) for i, (a, _) in zip(ids, res)},
                "answers": {str(i): a[v] for i, (a, _) in zip(ids, res)}}, ensure_ascii=False))
        book("jev", cost, slug=slug, posts=len(ids), input_tokens=tokens)
        print(f"{slug}: {len(ids)} posts, {tokens:,} tokens, ${cost:.4f}; ledger ${spent():.3f}", flush=True)


def jev_cost(n=30):
    """Measured price of one question variant alone: v2 and v3 each on n random candidates per
    hold-out event (the main runs asked both in one request, so their cost is for the pair)."""
    posts = R_posts()
    key = M.get_openrouter_key()
    guard()
    out, total = {}, 0.0
    rng = np.random.default_rng(3)
    for slug in C.HOLDOUT:
        cands = C.ranked_candidates(slug)
        ids = [cands[k] for k in rng.choice(len(cands), size=n, replace=False)]
        for v in ("v2", "v3"):
            q = {v: C.question(slug, v)}
            with ThreadPoolExecutor(10) as pool:
                res = list(pool.map(lambda i: ask_jev(key, q, posts[i]["text"][:C.POST_CHARS]), ids))
            tok = sum(u.get("input_tokens", 0) for _, u in res)
            usd = sum(u.get("cost", 0) for _, u in res) or tok * JEV_PRICE_PER_M / 1e6
            total += usd
            out.setdefault(slug, {})[v] = {"posts": n, "input_tokens": tok, "usd": usd,
                                           "usd_per_3000": usd / n * 3000}
            print(f"{slug} {v}: {tok / n:.0f} tokens/post, ${usd / n * 3000:.3f} per 3,000 posts", flush=True)
    (C.OUT / "jev_cost.json").write_text(json.dumps(out, indent=2))
    book("jev_cost", total, posts=n * 6)


# ------------------------------------------------------------------------------- cohere
COHERE_PRICE_PER_SEARCH = 0.002


def cohere():
    posts = R_posts()
    client = M.get_cohere_client()
    for slug in C.HOLDOUT:
        target = C.OUT / "cohere" / f"{slug}.json"
        if target.exists():
            continue
        guard()
        ids = C.ranked_candidates(slug)
        probes = json.loads(C.scores_path(slug).read_text())["probes"]
        docs = [posts[i]["text"][:C.POST_CHARS] or posts[i]["summary"] for i in ids]
        best = np.zeros(len(docs), np.float32)
        billed = 0
        for q in probes:
            for k in range(0, len(docs), 1000):
                chunk = docs[k:k + 1000]
                resp = M._call_with_retry(lambda: client.rerank(
                    model=M.RERANK_MODEL, query=q, documents=chunk, top_n=len(chunk),
                    max_tokens_per_doc=2048), what="rerank")
                billed += int(resp.meta.billed_units.search_units or 0)
                for r in resp.results:
                    best[k + r.index] = max(best[k + r.index], r.relevance_score)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"slug": slug, "model": M.RERANK_MODEL, "probes": probes,
                                      "p": {str(i): round(float(s), 4) for i, s in zip(ids, best)},
                                      "searches_billed": billed}))
        book("cohere", billed * COHERE_PRICE_PER_SEARCH, slug=slug, searches=billed)
        print(f"{slug}: {len(ids)} posts, {billed} searches, ${billed * COHERE_PRICE_PER_SEARCH:.2f}; "
              f"ledger ${spent():.3f}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["cosine", "jev", "jev_cost", "cohere"])
    ap.add_argument("--set", choices=["dev", "holdout"], default="dev")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    {"cosine": cosine, "jev": lambda: jev(a.set, a.limit), "jev_cost": jev_cost, "cohere": cohere}[a.step]()
