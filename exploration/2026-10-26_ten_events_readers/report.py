#!/usr/bin/env python
"""Free step: Jev v3 and the four readers on the ten events -> results.json and printed tables.

Per event: Jev AUC; F1 at the best possible cut, at the shared cut (one Jev threshold learned on
the five labelled dev events of jev_selection) and at the sample cut (100 posts drawn evenly from
ten equal-width Jev bands, the cut with the best F1 on them; 200 draws, mean). The sample cut is
set once with each reader's labels; F1, lost and extra are always counted on the Codex labels,
weighted back to the 3,000 candidates. A post a reader left unlabelled keeps Codex's label.
"""
from __future__ import annotations

import json

import numpy as np

import ten as T

C, R = T.C, T.R
import evaluate as V  # noqa: E402  (jev_selection/evaluate.py)

READERS = ["codex", "deepseek-v4-flash", "claude-haiku-5-5", "claude-sonnet-5-5"]
N = 100


def reader_labels(who, slug, truth):
    p = T.OUT / "reader_labels" / who / f"{slug}.json"
    if not p.exists():
        return None, {}
    d = json.loads(p.read_text())
    lab = {**truth, **{int(k): v for k, v in d["labels"].items()}}
    ids = sorted(truth)
    return lab, {"agree": sum(lab[i] == truth[i] for i in ids) / len(ids), "reader_on": sum(lab[i] for i in ids),
                 "codex_on": sum(truth[i] for i in ids), "missing": len(d["missing"]), "usd": d["usage"]["cost"]}


def main():
    posts, dev_labels = R.load_posts(), R.load_labels()
    dev = {s: V.dev_data(s, posts, dev_labels) for s in C.DEV}
    shared = V.pooled_cut(dev, "jev_v3")
    out = {"shared_cut": shared, "events": {}}
    for slug in T.EVENTS:
        truth, weight = T.labels(slug)
        s = T.jev(slug)
        ids = sorted(truth)
        oc = V.best_cut(ids, truth, weight, s)
        r = {"era": T.era(slug), "name": T.SHORT[slug], "labelled": len(ids),
             "on_event": sum(weight[i] for i in ids if truth[i]), "auc": V.auc(ids, truth, weight, s),
             "best": {"cut": oc, **V.counts(ids, truth, weight, s, oc)},
             "shared": {"cut": shared, **V.counts(ids, truth, weight, s, shared)}, "readers": {}}
        for who in READERS:
            lab, info = (truth, {}) if who == "codex" else reader_labels(who, slug, truth)
            if lab is None:
                continue
            rng = np.random.default_rng(17)
            res = [V.counts(ids, truth, weight, s, V.sample_cut(ids, truth, weight, s, N, rng, lab))
                   for _ in range(V.SEEDS)]
            r["readers"][who] = {**{k: float(np.mean([x[k] for x in res])) for k in ("f1", "lost", "extra")},
                                 "f1_p10": float(np.percentile([x["f1"] for x in res], 10)), **info}
        out["events"][slug] = r
    (T.HERE / "results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    show(out)


def show(out):
    ev = out["events"]
    print(f"shared cut (learned on the 5 dev events): {out['shared_cut']}\n")
    print("| Событие | о событии из 3 000 | AUC Jev v3 | F1, лучший возможный (порог) | F1, общий порог | F1, по выборке (Codex) |")
    print("|---|---|---|---|---|---|")
    for r in ev.values():
        on = f"{r['on_event']:,.0f}".replace(",", " ")
        print(f"| {r['name']} | ~{on} | {r['auc']:.2f} | {r['best']['f1']:.2f} ({r['best']['cut']:.2f}) | "
              f"{r['shared']['f1']:.2f} | {r['readers']['codex']['f1']:.2f} |")
    names = {"codex": "Codex", "deepseek-v4-flash": "DeepSeek", "claude-haiku-5-5": "Haiku",
             "claude-sonnet-5-5": "Sonnet"}
    who = [w for w in READERS if all(w in r["readers"] for r in ev.values())]
    h = " / ".join(names[w] for w in who)
    print(f"\n| Событие | F1: {h} | Потеряно: {h} | Лишних: {h} | Совпадение с Codex: {' / '.join(names[w] for w in who[1:])} |")
    print("|---|---|---|---|---|")
    for r in ev.values():
        rd = r["readers"]
        print(f"| {r['name']} | " + " / ".join(f"{rd[w]['f1']:.3f}" for w in who) + " | "
              + " / ".join(f"{rd[w]['lost']:.0f}" for w in who) + " | "
              + " / ".join(f"{rd[w]['extra']:.0f}" for w in who) + " | "
              + " / ".join(f"{rd[w]['agree']:.0%}" for w in who[1:]) + " |")
    print("\n| Эпоха | событий | AUC, среднее | F1 лучший − F1 по выборке Codex | " +
          " | ".join(f"F1 {names[w]} − F1 Codex" for w in who[1:]) + " |")
    print("|---|---|---|---|" + "---|" * len(who[1:]))
    for era in ("2020–2022", "2023–2025"):
        rs = [r for r in ev.values() if r["era"] == era]
        print(f"| {era} | {len(rs)} | {np.mean([r['auc'] for r in rs]):.2f} | "
              f"{np.mean([r['best']['f1'] - r['readers']['codex']['f1'] for r in rs]):+.3f} | "
              + " | ".join(f"{np.mean([r['readers'][w]['f1'] - r['readers']['codex']['f1'] for r in rs]):+.3f}"
                           for w in who[1:]) + " |")


if __name__ == "__main__":
    main()
