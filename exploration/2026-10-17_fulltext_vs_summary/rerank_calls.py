#!/usr/bin/env python
"""Paid step of rerank_eval.py: Cohere rerank-v3.5 scores for the labelled posts.

Per event and probe: the cleaned full text of every labelled post, and the summary of the
posts the pipeline never reranked. Writes data/interim/fulltext_vs_summary/rerank_<slug>.json
with each post's best score over the probes and the search units Cohere billed. Skips events
already written; stops before an event that would pass COST_CAP_USD.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rerank_eval as E  # noqa: E402
import run as R  # noqa: E402
from events_coverage import matching as M  # noqa: E402

COST_CAP_USD = 2.00
PRICE_PER_SEARCH = 0.002


def scored(client, queries, documents, billed):
    """Best score over the queries for each document, as the pipeline's per-probe mode."""
    if not documents:
        return np.zeros(0, np.float32)
    best = np.zeros(len(documents), np.float32)
    for query in queries:
        resp = M._call_with_retry(lambda: client.rerank(
            model=M.RERANK_MODEL, query=query, documents=documents, top_n=len(documents),
            max_tokens_per_doc=2048), what="rerank")
        billed.append(int(resp.meta.billed_units.search_units or 0))
        s = np.zeros(len(documents), np.float32)
        for r in resp.results:
            s[r.index] = r.relevance_score
        best = np.maximum(best, s)
    return best


def main():
    posts, labels = R.load_posts(), R.load_labels()
    client = M.get_cohere_client()
    spent = sum(json.loads(p.read_text())["searches_billed"] for p in R.OUT.glob("rerank_*.json"))
    for slug in R.EVENTS:
        target = R.OUT / f"rerank_{slug}.json"
        if target.exists():
            continue
        qs, ids, missing = E.work(slug, posts, labels)
        if spent * PRICE_PER_SEARCH > COST_CAP_USD - 0.5:
            raise SystemExit(f"stopping: {spent} searches billed so far")
        billed = []
        full = scored(client, qs, [posts[i]["text"] for i in ids], billed)
        summ = scored(client, qs, [E.summary_doc(posts[i]) for i in missing], billed)
        target.write_text(json.dumps({
            "slug": slug, "model": M.RERANK_MODEL, "probes": qs, "date": "2026-10-17",
            "fulltext": {str(i): round(float(v), 4) for i, v in zip(ids, full)},
            "summary_missing": {str(i): round(float(v), 4) for i, v in zip(missing, summ)},
            "searches_billed": sum(billed)}, ensure_ascii=False))
        spent += sum(billed)
        print(f"{slug}: {len(ids)} full texts, {len(missing)} summaries, {sum(billed)} searches "
              f"billed; total {spent} (${spent * PRICE_PER_SEARCH:.2f})", flush=True)


if __name__ == "__main__":
    main()
