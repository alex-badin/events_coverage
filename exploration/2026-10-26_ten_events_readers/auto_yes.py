#!/usr/bin/env python
"""Free check (03.11): are the candidates closest to the event by cosine similarity always "yes", so they
could skip the Decisions API? And is there a floor below which they are never "yes"?

Per event and rule (an absolute cosine threshold, or the top N by rank): how many of the 3,000 candidates
fall above it; the share the reference calls "yes" (majority of Sol, Astra and Fable on the 750 labelled
posts, weighted back to the 3,000); the share Decisions calls "yes" (p >= 0.5, variant shared_600, scored
on all 3,000); the share above Jev's cut-off (Jev on all 3,000, cut = the best possible cut against the
reference); and F1 when the posts above get score 1 without a call (variant choice_400_x400, Luna sample
cut). The same for the bottom of the list: candidates below a cosine floor or beyond rank N."""
from __future__ import annotations

import json

import numpy as np

import decisions_cost as D
import report as RP
import ten as T

V = RP.V
TOP_COS = [0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50]
TOP_N = [50, 100, 200, 500]
FLOOR_COS = [0.45, 0.50, 0.55, 0.60]
FLOOR_N = [2000, 2500]          # ranks beyond N


def event_data(slug):
    cos = {r["i"]: r["fulltext"] for r in json.loads(T.scores_path(slug).read_text())["rows"]}
    order = T.ranked(slug)
    maj, (_, w) = RP.majority(slug), T.labels(slug)
    ids = sorted(maj)
    jev = T.jev(slug)
    cut = V.best_cut(ids, maj, w, jev)
    return {"cos": cos, "order": order, "maj": maj, "w": w, "jev": jev, "jev_cut": cut,
            "dec": D.load("shared_600_candidates", slug)[0], "base": D.load("choice_400_x400", slug)[0]}


def measure(e, group, slug, auto_yes):
    lab = [i for i in e["maj"] if i in group]
    wsum = sum(e["w"][i] for i in lab)
    r = {"n": len(group), "share": len(group) / 3000,
         "ref_yes": sum(e["w"][i] for i in lab if e["maj"][i]) / wsum if wsum else None,
         "ref_no_est": sum(e["w"][i] for i in lab if not e["maj"][i]),
         "ref_yes_est": sum(e["w"][i] for i in lab if e["maj"][i]),
         "dec_yes": float(np.mean([e["dec"].get(i, 0) >= 0.5 for i in group])) if group else None,
         "jev_yes": float(np.mean([e["jev"][i] >= e["jev_cut"] for i in group])) if group else None}
    forced = {**e["base"], **{i: (1.0 if auto_yes else 0.0) for i in group}}
    r["f1_base"], r["f1_rule"] = D.evaluate(e["base"], slug)["f1"], D.evaluate(forced, slug)["f1"]
    return r


def main():
    out = {"top": {}, "floor": {}}
    for slug in T.EVENTS:
        e = event_data(slug)
        top = {f"cos>={t}": {i for i in e["order"] if e["cos"][i] >= t} for t in TOP_COS}
        top |= {f"top {n}": set(e["order"][:n]) for n in TOP_N}
        floor = {f"cos<{t}": {i for i in e["order"] if e["cos"][i] < t} for t in FLOOR_COS}
        floor |= {f"rank>{n}": set(e["order"][n:]) for n in FLOOR_N}
        out["top"][slug] = {k: measure(e, g, slug, True) for k, g in top.items()}
        out["floor"][slug] = {k: measure(e, g, slug, False) for k, g in floor.items()}
    (T.HERE / "auto_yes.json").write_text(json.dumps(out, indent=2))
    show(out)


def pct(x):
    return "—" if x is None else f"{x:.0%}"


def show(out):
    for part, title, rules in (("top", "сверху (автоматическое «да»)", [f"cos>={t}" for t in TOP_COS] + [f"top {n}" for n in TOP_N]),
                               ("floor", "снизу (автоматическое «нет»)", [f"cos<{t}" for t in FLOOR_COS] + [f"rank>{n}" for n in FLOOR_N])):
        print(f"\nСводка, {title}:\n")
        print("| Правило | пропущено из 30 000 | экономия | «нет» эталона среди них (оценка) | «да» эталона среди них (оценка) | "
              "F1, изменение в среднем | худшее событие |")
        print("|---|---|---|---|---|---|---|")
        for k in rules:
            rows = {s: out[part][s][k] for s in out[part]}
            n = sum(r["n"] for r in rows.values())
            d = {T.SHORT[s]: r["f1_rule"] - r["f1_base"] for s, r in rows.items()}
            worst = min(d, key=d.get)
            print(f"| {k} | {n} | {n / 30000:.1%} | {sum(r['ref_no_est'] for r in rows.values()):.0f} | "
                  f"{sum(r['ref_yes_est'] for r in rows.values()):.0f} | {np.mean(list(d.values())):+.4f} | "
                  f"{d[worst]:+.3f} ({worst.split(',')[0]}) |")
        print(f"\nПо событиям, {title}: постов в группе / доля «да» по эталону / по Decisions / по Jev\n")
        print("| Событие | " + " | ".join(rules) + " |")
        print("|---|" + "---|" * len(rules))
        for s, rr in out[part].items():
            print(f"| {T.SHORT[s].split(',')[0]} | " + " | ".join(
                f"{rr[k]['n']} / {pct(rr[k]['ref_yes'])} / {pct(rr[k]['dec_yes'])} / {pct(rr[k]['jev_yes'])}" if rr[k]['n'] else "0"
                for k in rules) + " |")


if __name__ == "__main__":
    main()
