#!/usr/bin/env python
"""Bake-off: Qwen3-Embedding-8B (new sidecar) vs Cohere embed-v3 (stored) retrieval.

For each labeled event we rank the WHOLE window by each embedding's max-probe cosine
and measure how efficiently it recovers the rerank-validated relevant set (the kept
dataset). Read-only; the only API spend is embedding the handful of event probes.

Cohere docs: loaded from the news DB (as the pipeline does).
Qwen3 docs  : the window slice extracted from the Neo sidecar (float16, 4096-d, native).
Qwen3 query : the probes embedded via OpenRouter with the Qwen3 query instruction.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from events_coverage import matching as M  # noqa: E402

SLICES = Path("/private/tmp/claude-501/-Users-alexbadin-GitHub--projects-events-coverage/"
              "fc16d645-b2d7-4c6c-86a3-4843362a40eb/scratchpad/slices")
PROC = ROOT / "data" / "processed"
QWEN_INSTRUCT = ("Given a news event description, retrieve news messages that report on "
                 "or discuss that event.")
KS = [300, 500, 1000, 2000, 3000, 5000]

EVENTS = ["kursk_2025w11", "trump_zelensky_2025w10"]


def openrouter_embed(texts, dim=4096):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env"); key = os.environ.get("OPENROUTER_API_KEY")
    body = json.dumps({"model": "qwen/qwen3-embedding-8b", "input": list(texts),
                       "provider": {"order": ["DeepInfra"], "allow_fallbacks": False}}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/embeddings", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {key}"); req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    data = sorted(resp["data"], key=lambda d: d["index"])
    return M.l2_normalize(np.asarray([d["embedding"] for d in data], dtype=np.float32))


def load_kept(slug):
    """Ground-truth relevant set: (source, message_id) of the kept dataset rows."""
    R = set()
    with open(PROC / f"event_{slug}_dataset.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            R.add((row["source"], str(row["message_id"])))
    return R


def load_manifest(slug):
    return json.loads((PROC / f"event_{slug}_manifest.json").read_text())


def recall_at(order_keys, R_in_pool, ks):
    """order_keys: pool keys sorted by score desc. Returns {K: recall}."""
    out, seen = {}, 0
    hits = 0
    R = R_in_pool
    ranked_hit = [1 if k in R else 0 for k in order_keys]
    cum = np.cumsum(ranked_hit)
    denom = max(1, len(R))
    for K in ks:
        out[K] = cum[min(K, len(cum)) - 1] / denom if len(cum) else 0.0
    return out


def auc(scores, labels):
    # rank-based AUC (Mann-Whitney)
    order = np.argsort(scores)
    ranks = np.empty(len(scores)); ranks[order] = np.arange(1, len(scores) + 1)
    pos = labels.sum()
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    return (ranks[labels == 1].sum() - pos * (pos + 1) / 2) / (pos * neg)


def run_event(slug, cohere_client):
    man = load_manifest(slug)
    ev = man["event"]
    probes = M.build_probes({"name": ev["name"], "quotes": ev["quotes"]})
    start = date.fromisoformat(man["window"]["match_start"])
    end = date.fromisoformat(man["window"]["match_end_exclusive"])
    R = load_kept(slug)

    # ---- Cohere: window docs from DB + probe embeddings
    recs, cmat = M.load_window_messages(start, end)
    ckeys = [(r["source"], str(r["message_id"])) for r in recs]
    cq = M.embed_texts(cohere_client, probes)
    cscore = (cmat @ cq.T).max(axis=1)
    corder = [ckeys[i] for i in np.argsort(-cscore)]
    R_c = R & set(ckeys)

    # ---- Qwen3: precomputed max-probe scores from Neo (query used the Qwen3 instruction;
    # docs are the intact sidecar vectors — computed there to avoid the flaky-link vector transfer)
    qkeys, qsc = [], []
    with open(SLICES / f"event_{slug}_qwen_scores.tsv", encoding="utf-8") as f:
        for line in f:
            mid, src, _, sc = line.rstrip("\n").split("\t")
            qkeys.append((src, mid)); qsc.append(float(sc))
    qscore = np.array(qsc)
    qorder = [qkeys[i] for i in np.argsort(-qscore)]
    R_q = R & set(qkeys)

    print(f"\n================ {slug} ================")
    print(f"event: {ev['name']}")
    print(f"probes: {len(probes)} | kept(R): {len(R)} | window pool  Cohere={len(ckeys):,}  Qwen3={len(qkeys):,}")
    print(f"R present in pool: Cohere {len(R_c)}/{len(R)}   Qwen3 {len(R_q)}/{len(R)}")
    rc = recall_at(corder, R_c, KS)
    rq = recall_at(qorder, R_q, KS)
    print(f"\n  Recall@K of the rerank-kept set (higher = fewer candidates needed):")
    print(f"  {'K':>6} | {'Cohere':>8} | {'Qwen3':>8}")
    for K in KS:
        print(f"  {K:>6} | {rc[K]*100:7.1f}% | {rq[K]*100:7.1f}%")
    ck = np.array([1 if k in R_c else 0 for k in ckeys])
    qk = np.array([1 if k in R_q else 0 for k in qkeys])
    print(f"\n  AUC (relevant vs rest):  Cohere {auc(cscore, ck):.3f}   Qwen3 {auc(qscore, qk):.3f}")


def main():
    client = M.get_cohere_client()
    for slug in EVENTS:
        run_event(slug, client)


if __name__ == "__main__":
    main()
