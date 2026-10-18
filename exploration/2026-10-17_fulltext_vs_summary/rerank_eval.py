#!/usr/bin/env python
"""Second step on full text: does rerank on the cleaned post text keep the on-event posts and
drop the off-event ones as well as rerank on `summary`, and does the 0.35 cut-off still fit?

Posts: every post the first step labelled (the union of both methods' top 500 plus the two
100-post samples from the top-3,000 zones), 772-809 per event; labels are the Codex ones.
Scores: the pipeline's rule — one rerank query per probe, a post keeps its best score.
  summary   from the 2026-08-03 `perphrase` candidates; posts missing there (below the
            cosine floor) are scored by rerank_calls.py on the same text the pipeline uses
  fulltext  rerank_calls.py on the cleaned text from texts.jsonl, one document per post
            (the longest is 4,072 characters, inside the 2,048-token document limit)

Steps (free; the paid calls live in rerank_calls.py):
  estimate  documents and searches the paid run needs
  report    kept / on-event kept / on-event lost per threshold -> results.json["rerank"]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run as R  # noqa: E402

csv.field_size_limit(10**9)
THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
DOCS_PER_SEARCH = 100


def summary_doc(post):
    return post["summary"] or post["text"]


def event_set(slug, posts, labels):
    """Labelled posts of one event: {post index: on-event?}."""
    out = {}
    for key in (slug, "deep_" + slug):
        for (s, i), yes in labels.items():
            if s == key:
                out[i] = out.get(i, False) or yes
    return out


def pipeline_summary_scores(slug):
    path = R.ROOT / "data/processed" / f"event_{slug}_qwen3_perphrase_candidates.csv"
    with path.open(encoding="utf-8") as f:
        return {(r["source"], r["message_id"]): float(r["rerank_score"]) for r in csv.DictReader(f)}


def probes(slug):
    return json.loads((R.OUT / f"scores_{slug}.json").read_text())["probes"]


def work(slug, posts, labels):
    """What the paid run must score: (probes, fulltext ids, summary ids missing a score)."""
    ids = sorted(event_set(slug, posts, labels))
    have = pipeline_summary_scores(slug)
    missing = [i for i in ids if (posts[i]["source"], posts[i]["message_id"]) not in have]
    return probes(slug), ids, missing


def estimate():
    posts, labels = R.load_posts(), R.load_labels()
    total = 0
    for slug in R.EVENTS:
        qs, ids, missing = work(slug, posts, labels)
        n = len(qs) * (math.ceil(len(ids) / DOCS_PER_SEARCH) + math.ceil(len(missing) / DOCS_PER_SEARCH))
        total += n
        print(f"{slug}: {len(qs)} probes, {len(ids)} full texts, {len(missing)} summaries -> {n} searches")
    print(f"total {total} searches, ${total * 2 / 1000:.2f} at $2 per 1,000 "
          "(more if Cohere bills long documents as several)")


def report():
    posts, labels = R.load_posts(), R.load_labels()
    results = json.loads((HERE / "results.json").read_text())
    out = {}
    for slug in R.EVENTS:
        truth = event_set(slug, posts, labels)
        paid = json.loads((R.OUT / f"rerank_{slug}.json").read_text())
        have = pipeline_summary_scores(slug)
        score = {"summary": {}, "fulltext": {int(i): v for i, v in paid["fulltext"].items()}}
        for i in truth:
            key = (posts[i]["source"], posts[i]["message_id"])
            score["summary"][i] = have[key] if key in have else paid["summary_missing"][str(i)]
        on = sum(truth.values())
        r = {"labelled": len(truth), "on_event": on, "searches_billed": paid["searches_billed"],
             "by_threshold": {}}
        for t in THRESHOLDS:
            row = {}
            for m in ("summary", "fulltext"):
                kept = [i for i in truth if score[m][i] >= t]
                hit = sum(truth[i] for i in kept)
                row[m] = {"kept": len(kept), "on_event_kept": hit, "on_event_lost": on - hit,
                          "off_event_kept": len(kept) - hit}
            r["by_threshold"][f"{t:.2f}"] = row
        out[slug] = r
        print(slug, f"labelled {len(truth)}, on-event {on}")
        for t, row in r["by_threshold"].items():
            print("  ", t, *(f"{m}: kept {v['kept']} on {v['on_event_kept']} lost {v['on_event_lost']} "
                             f"off {v['off_event_kept']}" for m, v in row.items()), sep="  ")
    results["rerank"] = out
    (HERE / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["estimate", "report"])
    {"estimate": estimate, "report": report}[ap.parse_args().step]()
