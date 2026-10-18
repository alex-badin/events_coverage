#!/usr/bin/env python
"""Free step: how well each scorer and each cut rule picks the on-event posts.

Scorers: Jev v0-v3 (common.question) and Cohere rerank-v3.5 on full text.
Cut rules:
  oracle      the best threshold for this event (upper bound, not usable)
  global      one threshold for all events, chosen on the other events (leave one out)
  sample_n    per event: a reader labels n posts drawn evenly from score bands
              (10 equal-width bands over the scorer's range), the threshold with the best
              F1 on that sample is used; repeated SEEDS times, mean and spread reported
Quality: F1 of the kept set, on-event posts lost, off-event posts kept. On hold-out events
labels are a stratified sample of the 3,000 candidates, so every count is weighted back to the
candidate list (`weight` = band size / labelled in band).
"""
from __future__ import annotations

import json
import sys

import numpy as np

import common as C

SEEDS = 200
BANDS = 10
SAMPLE_SIZES = [60, 100]


# ------------------------------------------------------------------------------- data
def dev_data(slug, posts, labels):
    truth = C.E.event_set(slug, posts, labels)
    scorers = {}
    v0 = C.R.OUT / f"jev_{slug}.json"
    if v0.exists():
        scorers["jev_v0"] = {int(k): v for k, v in json.loads(v0.read_text())["noul"].items()}
    for v in ("v1", "v2", "v3"):
        s = C.jev_scores(slug, v)
        if s:
            scorers[f"jev_{v}"] = s
    scorers["cohere"] = {int(k): v for k, v in
                         json.loads((C.R.OUT / f"rerank_{slug}.json").read_text())["fulltext"].items()}
    ids = sorted(i for i in truth if all(i in s for s in scorers.values()))
    return ids, {i: truth[i] for i in ids}, {i: 1.0 for i in ids}, scorers


def holdout_data(slug):
    lab = json.loads((C.OUT / "holdout_labels" / f"{slug}.json").read_text())
    truth = {int(k): v for k, v in lab["labels"].items()}
    weight = {int(k): v for k, v in lab["weights"].items()}
    scorers = {f"jev_{v}": C.jev_scores(slug, v) for v in ("v2", "v3")}
    scorers["cohere"] = {int(k): v for k, v in
                         json.loads((C.OUT / "cohere" / f"{slug}.json").read_text())["p"].items()}
    ids = sorted(truth)
    return ids, truth, weight, scorers


# ---------------------------------------------------------------------------- metrics
def counts(ids, truth, weight, score, cut):
    tp = sum(weight[i] for i in ids if truth[i] and score[i] >= cut)
    fp = sum(weight[i] for i in ids if not truth[i] and score[i] >= cut)
    on = sum(weight[i] for i in ids if truth[i])
    f1 = 2 * tp / (on + tp + fp) if on + tp + fp else 0.0
    return {"f1": f1, "lost": on - tp, "extra": fp, "kept": tp + fp}


def best_cut(ids, truth, weight, score):
    cands = sorted({round(score[i], 4) for i in ids})
    best = max(cands, key=lambda c: counts(ids, truth, weight, score, c)["f1"]) if cands else 0.5
    return best


def auc(ids, truth, weight, score):
    pos = [(score[i], weight[i]) for i in ids if truth[i]]
    neg = [(score[i], weight[i]) for i in ids if not truth[i]]
    if not pos or not neg:
        return float("nan")
    ns = np.array([s for s, _ in neg]); nw = np.array([w for _, w in neg])
    total = 0.0
    for s, w in pos:
        total += w * (nw[ns < s].sum() + 0.5 * nw[ns == s].sum())
    return total / (sum(w for _, w in pos) * nw.sum())


def sample_cut(ids, truth, weight, score, n, rng, reader=None):
    """Threshold from n labelled posts drawn evenly from equal-width score bands.
    Each band's draw is weighted back to the band's share of the candidate list.
    reader: the labels the cut is picked on (default: the reference labels themselves)."""
    lo, hi = min(score[i] for i in ids), max(score[i] for i in ids)
    edges = np.linspace(lo, hi, BANDS + 1)
    band = {i: min(int(np.searchsorted(edges, score[i], side="right")) - 1, BANDS - 1) for i in ids}
    members = {b: [i for i in ids if band[i] == b] for b in range(BANDS)}
    per = max(1, n // BANDS)
    picked, w = [], {}
    for b, m in members.items():
        if not m:
            continue
        p = np.array([weight[i] for i in m], float); p /= p.sum()
        take = rng.choice(len(m), size=min(per, len(m)), replace=False, p=p)
        mass = sum(weight[i] for i in m)
        for t in take:
            picked.append(m[t]); w[m[t]] = mass / len(take)
    return best_cut(picked, reader if reader is not None else truth, w, score)


# ----------------------------------------------------------------------------- report
def pooled_cut(events, name):
    pool_ids = [(o, i) for o, d in events.items() for i in d[0]]
    pt = {(o, i): d[1][i] for o, d in events.items() for i in d[0]}
    pw = {(o, i): d[2][i] for o, d in events.items() for i in d[0]}
    ps = {(o, i): d[3][name][i] for o, d in events.items() for i in d[0]}
    return best_cut(pool_ids, pt, pw, ps)


def evaluate(events, fixed_cuts=None):
    """events: {slug: (ids, truth, weight, scorers)} -> rows. fixed_cuts: {scorer: cut} learned
    elsewhere (the dev events) replaces the leave-one-out global cut."""
    names = sorted(set.intersection(*[set(d[3]) for d in events.values()]))
    rows = {}
    for name in names:
        for slug, (ids, truth, weight, scorers) in events.items():
            s = scorers[name]
            r = {"auc": auc(ids, truth, weight, s)}
            oc = best_cut(ids, truth, weight, s)
            r["oracle"] = {"cut": oc, **counts(ids, truth, weight, s, oc)}
            if fixed_cuts:
                gc = fixed_cuts[name]
            else:
                gc = pooled_cut({o: d for o, d in events.items() if o != slug}, name)
            r["global"] = {"cut": gc, **counts(ids, truth, weight, s, gc)}
            if name == "cohere":
                r["pipeline_0.35"] = {"cut": 0.35, **counts(ids, truth, weight, s, 0.35)}
            for n in SAMPLE_SIZES:
                rng = np.random.default_rng(17)
                res = [counts(ids, truth, weight, s, sample_cut(ids, truth, weight, s, n, rng)) for _ in range(SEEDS)]
                r[f"sample_{n}"] = {k: float(np.mean([x[k] for x in res])) for k in ("f1", "lost", "extra")}
                r[f"sample_{n}"]["f1_p10"] = float(np.percentile([x["f1"] for x in res], 10))
            r["on_event"] = sum(weight[i] for i in ids if truth[i])
            r["off_event"] = sum(weight[i] for i in ids if not truth[i])
            rows.setdefault(name, {})[slug] = r
    return rows


def show(rows):
    for name, per in rows.items():
        print(f"\n== {name}")
        print(f"{'event':28} {'on':>6} {'AUC':>5} | {'oracle F1 cut':>14} | {'global F1 lost extra':>21} | "
              + " | ".join(f"{'sample'+str(n)+' F1 p10 lost extra':>27}" for n in SAMPLE_SIZES))
        for slug, r in per.items():
            g = r.get("global")
            gs = f"{g['f1']:.3f} {g['lost']:5.0f} {g['extra']:5.0f}" if g else "-"
            ss = " | ".join(f"{r[f'sample_{n}']['f1']:.3f} {r[f'sample_{n}']['f1_p10']:.3f} "
                            f"{r[f'sample_{n}']['lost']:5.0f} {r[f'sample_{n}']['extra']:5.0f}".rjust(27)
                            for n in SAMPLE_SIZES)
            if "pipeline_0.35" in r:
                q = r["pipeline_0.35"]
                print(f"{'  (pipeline cut 0.35)':28} F1 {q['f1']:.3f} lost {q['lost']:.0f} extra {q['extra']:.0f}")
            print(f"{slug:28} {r['on_event']:6.0f} {r['auc']:.3f} | {r['oracle']['f1']:.3f} {r['oracle']['cut']:8.3f} | "
                  f"{gs:>21} | {ss}")


READERS = ["codex", "deepseek-v4-flash", "qwen3.8-flash"]


def readers(events, name="jev_v3", n=100):
    """sample_n with each API reader's labels picking the cut; F1, lost and extra are still
    measured on the Codex labels. A post the reader left unlabelled keeps Codex's label."""
    rows = {}
    for slug, (ids, truth, weight, scorers) in events.items():
        s = scorers[name]
        for who in READERS:
            if who == "codex":
                lab, info = truth, {}
            else:
                d = json.loads((C.OUT / "reader_labels" / who / f"{slug}.json").read_text())
                lab = {**truth, **{int(k): v for k, v in d["labels"].items()}}
                info = {"agree": sum(lab[i] == truth[i] for i in ids) / len(ids),
                        "reader_on": sum(lab[i] for i in ids), "codex_on": sum(truth[i] for i in ids),
                        "usd_all": d["usage"]["cost"], "usd_per_100": d["usage"]["cost"] / len(ids) * n,
                        "missing": len(d["missing"])}
            rng = np.random.default_rng(17)
            res = [counts(ids, truth, weight, s, sample_cut(ids, truth, weight, s, n, rng, lab)) for _ in range(SEEDS)]
            r = {k: float(np.mean([x[k] for x in res])) for k in ("f1", "lost", "extra")}
            r["f1_p10"] = float(np.percentile([x["f1"] for x in res], 10))
            r["oracle_f1"] = counts(ids, truth, weight, s, best_cut(ids, truth, weight, s))["f1"]
            rows.setdefault(slug, {})[who] = {**r, **info}
            print(f"{slug:28} {who:18} F1 {r['f1']:.3f} p10 {r['f1_p10']:.3f} lost {r['lost']:5.0f} "
                  f"extra {r['extra']:5.0f}  " + " ".join(f"{k} {v:.4g}" for k, v in info.items()))
    return rows


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    posts, labels = C.R.load_posts(), C.R.load_labels()
    dev = {s: dev_data(s, posts, labels) for s in C.DEV}
    if which == "readers":
        rows = readers({**dev, **{s: holdout_data(s) for s in C.HOLDOUT}})
        (C.OUT / "evaluation_readers.json").write_text(json.dumps(rows, indent=2))
        raise SystemExit
    if which == "dev":
        rows = evaluate(dev)
    else:
        events = {s: holdout_data(s) for s in C.HOLDOUT}
        cuts = {n: pooled_cut(dev, n) for n in events[C.EVENTS[-1]][3]}
        print("cuts learned on the dev events:", cuts)
        rows = evaluate(events, cuts)
    show(rows)
    (C.OUT / f"evaluation_{which}.json").write_text(json.dumps(rows, indent=2))
