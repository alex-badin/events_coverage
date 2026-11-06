#!/usr/bin/env python
"""F1 of Codex Luna's direct labels on the ten control events, against the majority of Sol, Astra and Fable,
beside API Luna's direct labels and Decisions with the Luna sample cut-off. Weighted to 3,000 candidates."""
import json, sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-10-26_ten_events_readers"))
import report as RP, ten as T, decisions_cost as D  # noqa: E402

OUT = HERE.parents[1] / "data" / "interim" / "luna_direct" / "control" / "out"


def f1(lab, maj, w):
    ids = [i for i in maj if i in lab]
    tp = sum(w[i] for i in ids if lab[i] and maj[i]); fp = sum(w[i] for i in ids if lab[i] and not maj[i])
    fn = sum(w[i] for i in ids if not lab[i] and maj[i])
    return 2 * tp / (2 * tp + fp + fn), len(ids), tp + fp


rows = []
print("event | answered | Codex Luna F1 | API Luna F1 | Decisions F1 | same label Codex/API | yes est. Codex | yes est. API")
for slug in T.EVENTS:
    maj, (_, w) = RP.majority(slug), T.labels(slug)
    codex = {}
    for p in OUT.glob(f"{slug}_*.json"):
        if p.stat().st_size:
            codex.update({int(x["id"]): x["label"] == "yes" for x in json.loads(p.read_text())["labels"] if str(x["id"]).isdigit()})
    api = {int(k): v for k, v in json.loads((T.OUT / "reader_labels" / "gpt-6-luna" / f"{slug}.json").read_text())["labels"].items()}
    fc, n, yc = f1(codex, maj, w)
    fa, _, ya = f1(api, maj, w)
    dec = D.evaluate(D.load("choice_400_x400", slug)[0], slug)["f1"]
    same = np.mean([codex[i] == api[i] for i in codex if i in api])
    rows.append((fc, fa, dec, same))
    print(f"{slug} | {n} | {fc:.3f} | {fa:.3f} | {dec:.3f} | {same:.3f} | {yc:.0f} | {ya:.0f}")
print("mean", np.mean(rows, axis=0).round(3))
