#!/usr/bin/env python
"""F1 of each Codex Luna variant on the four control events, beside the API Luna direct labels and Decisions."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-10-26_ten_events_readers"))
import report as RP, ten as T, decisions_cost as D  # noqa: E402
S = HERE.parents[1] / "data" / "interim" / "luna_direct"


def load(folder, slug):
    lab = {}
    for p in folder.glob(f"{slug}_*.json"):
        if p.stat().st_size:
            lab.update({int(x["id"]): x["label"] == "yes" for x in json.loads(p.read_text())["labels"] if str(x["id"]).isdigit()})
    return lab


def f1(lab, maj, w):
    ids = [i for i in maj if i in lab]
    tp = sum(w[i] for i in ids if lab[i] and maj[i]); fp = sum(w[i] for i in ids if lab[i] and not maj[i])
    fn = sum(w[i] for i in ids if not lab[i] and maj[i])
    return f"{2 * tp / (2 * tp + fp + fn):.3f} ({len(ids)})" if ids else "-"


if __name__ == "__main__":
    print("event | Codex first | rerun | bare | brief | API Luna | API Luna+brief | Decisions")
    for slug in ["trump_statements_2025w10", "drones_moscow_2025w11", "putin_lukashenko_2025w11", "mishustin_government_2020w03"]:
        maj, (_, w) = RP.majority(slug), T.labels(slug)
        cols = [load(S / "control" / "out", slug)] + [load(S / "variants" / v, slug) for v in ("rerun", "bare", "brief")]
        api = [{int(k): v for k, v in json.loads((T.OUT / "reader_labels" / who / f"{slug}.json").read_text())["labels"].items()} for who in ("gpt-6-luna", "gpt-6-luna+brief")]
        print(slug, "|", " | ".join(f1(c, maj, w) for c in cols + api), "|", f"{D.evaluate(D.load('choice_400_x400', slug)[0], slug)['f1']:.3f}")
