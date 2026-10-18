#!/usr/bin/env python
"""Free step: Jev's yes-probability against the Codex labels, next to Cohere full-text rerank.

Same posts and counts as `rerank_eval.py report`: kept / on-event kept / on-event lost /
off-event kept, per cut-off. Writes results.json["jev"].
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rerank_eval as E  # noqa: E402
import run as R  # noqa: E402

JEV_CUTS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
COHERE_CUT = 0.35


def counts(truth, score, cut):
    kept = [i for i in truth if score[i] >= cut]
    hit = sum(truth[i] for i in kept)
    on = sum(truth.values())
    return {"kept": len(kept), "on_event_kept": hit, "on_event_lost": on - hit, "off_event_kept": len(kept) - hit}


def main():
    posts, labels = R.load_posts(), R.load_labels()
    results = json.loads((HERE / "results.json").read_text())
    out = {}
    for slug in R.EVENTS:
        path = R.OUT / f"jev_{slug}.json"
        if not path.exists():
            continue
        jev = {int(k): v for k, v in json.loads(path.read_text())["noul"].items()}
        cohere = {int(k): v for k, v in json.loads((R.OUT / f"rerank_{slug}.json").read_text())["fulltext"].items()}
        truth = {i: y for i, y in E.event_set(slug, posts, labels).items() if i in jev}
        r = {"labelled": len(truth), "on_event": sum(truth.values()),
             "cohere_fulltext_0.35": counts(truth, cohere, COHERE_CUT),
             "jev": {f"{c:.1f}": counts(truth, jev, c) for c in JEV_CUTS}}
        out[slug] = r
        print(f"{slug}: labelled {r['labelled']}, on-event {r['on_event']}")
        print(f"   cohere 0.35  {r['cohere_fulltext_0.35']}")
        for c, row in r["jev"].items():
            print(f"   jev {c}      {row}")
    results["jev"] = out
    (HERE / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
