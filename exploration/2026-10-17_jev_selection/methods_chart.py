#!/usr/bin/env python
"""Free step: every selection method on the three hold-out events -> methods.json and two charts
(F1 against cost per event, recall against precision).

Precision, recall and F1 are per event (weighted estimates for all 3,000 candidates), then
averaged over the three events with equal weight. Sample-based methods: 200 draws of 100 posts per
event, the pooled numbers averaged over draws. Cost: mean per event on 3,000 candidates.
"""
import json

import numpy as np

import common as C
import evaluate as V

PRICE_SOL_IN = 2.0          # gpt-6.1-sol, $ per 1M input tokens (OpenAI price, 13.10.2026)
PRICE_SOL_OUT = 10.0


def measured_costs():
    spend = [json.loads(l) for l in (C.OUT / "spend.jsonl").read_text().splitlines() if l.strip()]
    cohere = np.mean([s["usd"] for s in spend if s["step"] == "cohere"])
    jc = json.loads((C.OUT / "jev_cost.json").read_text())
    jev = {v: np.mean([jc[s][v]["usd_per_3000"] for s in C.HOLDOUT]) for v in ("v2", "v3")}
    readers = {}
    for who in ("deepseek-v4-flash", "qwen3.8-flash"):
        per = []
        for s in C.HOLDOUT:
            d = json.loads((C.OUT / "reader_labels" / who / f"{s}.json").read_text())
            per.append(d["usage"]["cost"] / len(d["labels"]) * 100)
        readers[who] = float(np.mean(per))
    # estimates, not measured: a gpt-6.1-sol call writing the brief, and Codex as an API reader
    brief_tokens = np.mean([len((C.OUT / "briefs" / "prompts" / f"{s}.txt").read_text()) / 2.5 for s in C.HOLDOUT])
    brief = brief_tokens * PRICE_SOL_IN / 1e6 + 600 * PRICE_SOL_OUT / 1e6
    ds_in = np.mean([json.loads((C.OUT / "reader_labels" / "deepseek-v4-flash" / f"{s}.json").read_text())["usage"]["prompt_tokens"]
                     / 750 * 100 for s in C.HOLDOUT])
    readers["codex"] = ds_in * PRICE_SOL_IN / 1e6 + 100 * 20 * PRICE_SOL_OUT / 1e6
    return {"cohere": float(cohere), "jev_v2": float(jev["v2"]), "jev_v3": float(jev["v3"]),
            "brief": float(brief), "readers": readers}


def pooled(rows):
    """Mean over events of precision, recall and F1, each event weighted equally (pooling the
    counts would let the Trump event, ~2,456 on-event posts, outweigh the other two)."""
    ps, rs, fs = [], [], []
    for x in rows:
        p = x["tp"] / (x["tp"] + x["fp"]) if x["tp"] + x["fp"] else 0.0
        r = x["tp"] / x["on"]
        ps.append(p); rs.append(r); fs.append(2 * p * r / (p + r) if p + r else 0.0)
    return float(np.mean(ps)), float(np.mean(rs)), float(np.mean(fs))


def raw(ids, truth, weight, score, cut):
    tp = sum(weight[i] for i in ids if truth[i] and score[i] >= cut)
    fp = sum(weight[i] for i in ids if not truth[i] and score[i] >= cut)
    return {"tp": tp, "fp": fp, "on": sum(weight[i] for i in ids if truth[i])}


def reader_labels(who, slug, truth):
    if who == "codex":
        return truth
    d = json.loads((C.OUT / "reader_labels" / who / f"{slug}.json").read_text())
    return {**truth, **{int(k): v for k, v in d["labels"].items()}}


def main():
    posts, labels = C.R.load_posts(), C.R.load_labels()
    dev = {s: V.dev_data(s, posts, labels) for s in C.DEV}
    hold = {s: V.holdout_data(s) for s in C.HOLDOUT}
    cost = measured_costs()
    methods = []

    def fixed(label, scorer, cut, usd, kind):
        p, r, f = pooled([raw(*hold[s][:3], hold[s][3][scorer], cut) for s in C.HOLDOUT])
        methods.append({"method": label, "precision": p, "recall": r, "f1": f, "usd": usd, "kind": kind})

    def sampled(label, scorer, who, usd, kind):
        rngs = {s: np.random.default_rng(17) for s in C.HOLDOUT}
        P, Rc, F = [], [], []
        for _ in range(V.SEEDS):
            rows = []
            for s in C.HOLDOUT:
                ids, truth, weight, sc = hold[s]
                cut = V.sample_cut(ids, truth, weight, sc[scorer], 100, rngs[s], reader_labels(who, s, truth))
                rows.append(raw(ids, truth, weight, sc[scorer], cut))
            p, r, f = pooled(rows)
            P.append(p); Rc.append(r); F.append(f)
        methods.append({"method": label, "precision": float(np.mean(P)), "recall": float(np.mean(Rc)),
                        "f1": float(np.mean(F)), "usd": usd, "kind": kind})

    c, b, rd = cost["cohere"], cost["brief"], cost["readers"]
    fixed("Cohere, порог 0.35 (конвейер)", "cohere", 0.35, c, "cohere")
    fixed(f"Cohere, общий порог {V.pooled_cut(dev, 'cohere'):.2f}", "cohere", V.pooled_cut(dev, "cohere"), c, "cohere")
    sampled("Cohere + 100 постов читает Codex", "cohere", "codex", c + rd["codex"], "cohere")
    sampled("Cohere + 100 постов читает DeepSeek", "cohere", "deepseek-v4-flash", c + rd["deepseek-v4-flash"], "cohere")
    for v, name in (("v2", "Jev v2 (выбор)"), ("v3", "Jev v3 (да/нет)")):
        jc = cost[f"jev_{v}"] + b
        g = V.pooled_cut(dev, f"jev_{v}")
        fixed(f"{name}, общий порог {g:.2f}", f"jev_{v}", g, jc, "jev")
        sampled(f"{name} + 100 постов читает Codex", f"jev_{v}", "codex", jc + rd["codex"], "jev")
    jc = cost["jev_v3"] + b
    sampled("Jev v3 + 100 постов читает DeepSeek", "jev_v3", "deepseek-v4-flash", jc + rd["deepseek-v4-flash"], "jev")
    sampled("Jev v3 + 100 постов читает Qwen", "jev_v3", "qwen3.8-flash", jc + rd["qwen3.8-flash"], "jev")
    (C.OUT / "methods.json").write_text(json.dumps({"cost": cost, "methods": methods}, indent=2, ensure_ascii=False))
    for m in methods:
        print(f"{m['method']:42} P {m['precision']:.3f} R {m['recall']:.3f} F1 {m['f1']:.3f} ${m['usd']:.3f}")
    print(json.dumps(cost, indent=1))


if __name__ == "__main__":
    main()
