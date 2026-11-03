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

READERS = ["codex", "deepseek-v4-flash", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-haiku-5-5+brief",
           "claude-sonnet-5-5+brief", "gpt-6-luna", "gpt-6-luna+brief", "gpt-6.1-terra", "gpt-6.1-terra+brief",
           "gpt-6.1-sol", "gpt-6.1-sol+brief"]
FIRST = READERS[:4]   # the readers of the first run (26.10)
NAMES = {"codex": "Codex", "deepseek-v4-flash": "DeepSeek", "claude-haiku-5-5": "Haiku",
         "claude-sonnet-5-5": "Sonnet", "claude-haiku-5-5+brief": "Haiku+описание",
         "claude-sonnet-5-5+brief": "Sonnet+описание", "gpt-6-luna": "Luna", "gpt-6-luna+brief": "Luna+описание",
         "gpt-6.1-terra": "Terra", "gpt-6.1-terra+brief": "Terra+описание", "gpt-6.1-sol": "Sol",
         "gpt-6.1-sol+brief": "Sol+описание"}
N = 100


def reader_labels(who, slug, truth):
    p = T.OUT / "reader_labels" / who / f"{slug}.json"
    if not p.exists():
        return None, {}
    d = json.loads(p.read_text())
    if len(d["missing"]) > 0.02 * len(truth):   # unfinished run: filling the gaps with Codex labels would flatter it
        return None, {}
    lab = {**truth, **{int(k): v for k, v in d["labels"].items()}}
    ids = sorted(truth)
    return lab, {"agree": sum(lab[i] == truth[i] for i in ids) / len(ids), "reader_on": sum(lab[i] for i in ids),
                 "codex_on": sum(truth[i] for i in ids), "missing": len(d["missing"]), "usd": d["usage"]["cost"]}


def astra_labels(slug, judge="astra"):
    """Second reference: gpt-6-astra via Codex on the same posts and prompt (judges/astra/out/).
    judge="fable": the third, Claude Fable 5.1 on the same prompt files (judges/fable/out/)."""
    labels = {}
    for p in sorted((T.OUT / "judges" / judge / "out").glob(f"{slug}_[0-9][0-9][0-9].json")):
        for item in json.loads(p.read_text())["labels"]:
            if str(item["id"]).strip().isdigit():
                labels[int(str(item["id"]).strip())] = item["label"] == "yes"
    return labels


def majority(slug):
    """Majority of Sol, Astra and Fable on the 750 posts, or None while Fable's labels are incomplete."""
    sol, _ = T.labels(slug)
    astra, fable = astra_labels(slug), astra_labels(slug, "fable")
    if any(i not in astra or i not in fable for i in sol):
        return None
    return {i: sol[i] + astra[i] + fable[i] >= 2 for i in sol}


def other_references(out):
    """Every reader again against Astra alone, against the posts where Sol and Astra agree and against
    the majority of Sol, Astra and Fable. Agreed-only: disagreements are dropped and the kept posts'
    weights scaled so each weight group (one per rank band; the two deepest bands share a weight)
    keeps its total."""
    out["judges"], out["by_reference"] = {}, {"astra": {}, "agreed": {}, "majority": {}}
    for slug in T.EVENTS:
        sol, weight = T.labels(slug)
        astra, fable = astra_labels(slug), astra_labels(slug, "fable")
        ids = sorted(sol)
        if any(i not in astra for i in ids):
            print(f"{slug}: Astra labels incomplete, skipped"); continue
        out["judges"][slug] = {"agree": sum(sol[i] == astra[i] for i in ids) / len(ids),
                               "sol_on": sum(sol[i] for i in ids), "astra_on": sum(astra[i] for i in ids)}
        kept = [i for i in ids if sol[i] == astra[i]]
        scale = {w: sum(1 for i in ids if weight[i] == w) / max(1, sum(1 for i in kept if weight[i] == w))
                 for w in set(weight.values())}
        refs = {"astra": (ids, astra, weight),
                "agreed": (kept, {i: sol[i] for i in kept}, {i: weight[i] * scale[weight[i]] for i in kept})}
        maj = majority(slug)
        if maj is None:
            print(f"{slug}: Fable labels incomplete, no majority reference")
        else:
            refs["majority"] = (ids, maj, weight)
            out["judges"][slug].update(
                fable_on=sum(fable[i] for i in ids), majority_on=sum(maj[i] for i in ids),
                agree_sol_fable=sum(sol[i] == fable[i] for i in ids) / len(ids),
                agree_astra_fable=sum(astra[i] == fable[i] for i in ids) / len(ids),
                unanimous=sum(sol[i] == astra[i] == fable[i] for i in ids) / len(ids))
        s = T.jev(slug)
        for ref, (rid, truth, w) in refs.items():
            row = {"on_event": sum(w[i] for i in rid if truth[i]),
                   "best_f1": V.counts(rid, truth, w, s, V.best_cut(rid, truth, w, s))["f1"]}
            for who in ["reference", "codex", "astra"] + READERS[1:]:
                if who == "reference":
                    src = truth
                elif who == "codex":
                    src = sol
                elif who == "astra":
                    src = astra
                else:
                    p = T.OUT / "reader_labels" / who / f"{slug}.json"
                    if not p.exists():
                        continue
                    d = json.loads(p.read_text())
                    if len(d["missing"]) > 0.02 * len(ids):
                        continue
                    src = {int(k): v for k, v in d["labels"].items()}
                lab = {**truth, **{i: v for i, v in src.items() if i in truth}}
                rng = np.random.default_rng(17)
                res = [V.counts(rid, truth, w, s, V.sample_cut(rid, truth, w, s, N, rng, lab)) for _ in range(V.SEEDS)]
                row[who] = {**{k: float(np.mean([x[k] for x in res])) for k in ("f1", "lost", "extra")},
                            "agree": sum(lab[i] == truth[i] for i in rid) / len(rid)}
            out["by_reference"][ref][slug] = row


def scorers(out):
    """Jev v3 against the OpenAI Decisions API (same question, gpt-6-luna) on the 750 labelled posts:
    AUC, best possible F1, F1 at the sample cut set by Codex labels and by gpt-6-luna labels."""
    out["scorers"] = {}
    for slug in T.EVENTS:
        p = T.OUT / "decisions" / f"{slug}.json"
        if not p.exists():
            continue
        truth, weight = T.labels(slug)
        ids = sorted(truth)
        luna = json.loads((T.OUT / "reader_labels" / "gpt-6-luna" / f"{slug}.json").read_text())["labels"]
        luna_raw = {int(k): v for k, v in luna.items()}
        luna = {**truth, **luna_raw}
        row = {}
        for name, s in (("jev", T.jev(slug)),
                        ("decisions", {int(k): v for k, v in json.loads(p.read_text())["p"].items()})):
            r = {"auc": V.auc(ids, truth, weight, s),
                 "best": V.counts(ids, truth, weight, s, V.best_cut(ids, truth, weight, s))["f1"]}
            for who, lab in (("codex", truth), ("luna", luna)):
                rng = np.random.default_rng(17)
                res = [V.counts(ids, truth, weight, s, V.sample_cut(ids, truth, weight, s, N, rng, lab))
                       for _ in range(V.SEEDS)]
                r[f"sample_{who}"] = {k: float(np.mean([x[k] for x in res])) for k in ("f1", "lost", "extra")}
            maj = majority(slug)
            if maj is not None:   # the same, measured against the majority of Sol, Astra and Fable
                lab = {**maj, **{i: v for i, v in luna_raw.items() if i in maj}}
                rng = np.random.default_rng(17)
                res = [V.counts(ids, maj, weight, s, V.sample_cut(ids, maj, weight, s, N, rng, lab))
                       for _ in range(V.SEEDS)]
                r["majority"] = {"auc": V.auc(ids, maj, weight, s),
                                 "best": V.counts(ids, maj, weight, s, V.best_cut(ids, maj, weight, s))["f1"],
                                 "sample_luna": {k: float(np.mean([x[k] for x in res])) for k in ("f1", "lost", "extra")}}
            row[name] = r
        out["scorers"][slug] = row


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
    other_references(out)
    scorers(out)
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
    names = NAMES
    who = [w for w in FIRST if all(w in r["readers"] for r in ev.values())]
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
    more = [w for w in READERS if all(w in r["readers"] for r in ev.values())]
    print("\n| Событие | " + " | ".join(names[w] for w in more) + " |")
    print("|---|" + "---|" * len(more))
    for r in ev.values():
        print(f"| {r['name']} | " + " | ".join(f"{r['readers'][w]['f1']:.3f}" for w in more) + " |")
    print("\n| Читатель | F1 − F1 Codex: среднее | худшее событие | событий с отставанием > 0.02 | "
          "совпадение с Codex, среднее (мин.) | $ за 100 постов |")
    print("|---|---|---|---|---|---|")
    for w in more[1:]:
        gaps = {r["name"]: r["readers"][w]["f1"] - r["readers"]["codex"]["f1"] for r in ev.values()}
        worst = min(gaps, key=gaps.get)
        agree = [r["readers"][w]["agree"] for r in ev.values()]
        usd = sum(r["readers"][w]["usd"] for r in ev.values()) / sum(r["labelled"] for r in ev.values()) * N
        print(f"| {names[w]} | {np.mean(list(gaps.values())):+.3f} | {gaps[worst]:+.3f} ({worst}) | "
              f"{sum(g < -0.02 for g in gaps.values())} из {len(gaps)} | {np.mean(agree):.0%} ({min(agree):.0%}) | "
              f"{usd:.4f} |")
    if out.get("scorers"):
        print("\n| Событие | AUC: Jev / Decisions | F1 лучший: Jev / Decisions | F1 по выборке Codex: Jev / Decisions | "
              "F1 по выборке Luna: Jev / Decisions | потеряно / лишних, Luna: Jev | Decisions |")
        print("|---|---|---|---|---|---|")
        for slug, r in out["scorers"].items():
            j, d = r["jev"], r["decisions"]
            print(f"| {ev[slug]['name']} | {j['auc']:.2f} / {d['auc']:.2f} | {j['best']:.3f} / {d['best']:.3f} | "
                  f"{j['sample_codex']['f1']:.3f} / {d['sample_codex']['f1']:.3f} | "
                  f"{j['sample_luna']['f1']:.3f} / {d['sample_luna']['f1']:.3f} | "
                  f"{j['sample_luna']['lost']:.0f} / {j['sample_luna']['extra']:.0f} | "
                  f"{d['sample_luna']['lost']:.0f} / {d['sample_luna']['extra']:.0f} |")
        rs = list(out["scorers"].values())
        print("| среднее | " + " / ".join(f"{np.mean([r[n]['auc'] for r in rs]):.3f}" for n in ("jev", "decisions"))
              + " | " + " / ".join(f"{np.mean([r[n]['best'] for r in rs]):.3f}" for n in ("jev", "decisions"))
              + " | " + " / ".join(f"{np.mean([r[n]['sample_codex']['f1'] for r in rs]):.3f}" for n in ("jev", "decisions"))
              + " | " + " / ".join(f"{np.mean([r[n]['sample_luna']['f1'] for r in rs]):.3f}" for n in ("jev", "decisions"))
              + " | | |")
        rs = {slug: r for slug, r in out["scorers"].items() if "majority" in r["jev"]}
        if rs:
            print("\nJev против Decisions, эталон — большинство Sol, Astra и Fable:\n")
            print("| Событие | AUC: Jev / Decisions | F1 лучший: Jev / Decisions | F1 по выборке Luna: Jev / Decisions | "
                  "потеряно / лишних, Luna: Jev | Decisions |")
            print("|---|---|---|---|---|---|")
            for slug, r in rs.items():
                j, d = r["jev"]["majority"], r["decisions"]["majority"]
                print(f"| {ev[slug]['name']} | {j['auc']:.2f} / {d['auc']:.2f} | {j['best']:.3f} / {d['best']:.3f} | "
                      f"{j['sample_luna']['f1']:.3f} / {d['sample_luna']['f1']:.3f} | "
                      f"{j['sample_luna']['lost']:.0f} / {j['sample_luna']['extra']:.0f} | "
                      f"{d['sample_luna']['lost']:.0f} / {d['sample_luna']['extra']:.0f} |")
            m = [r[n]["majority"] for r in rs.values() for n in ("jev",)], [r["decisions"]["majority"] for r in rs.values()]
            print("| среднее | " + " / ".join(f"{np.mean([x['auc'] for x in g]):.3f}" for g in m)
                  + " | " + " / ".join(f"{np.mean([x['best'] for x in g]):.3f}" for g in m)
                  + " | " + " / ".join(f"{np.mean([x['sample_luna']['f1'] for x in g]):.3f}" for g in m) + " | | |")
    if not out.get("judges"):
        return
    print("\n| Событие | совпадение Sol и Astra | «да» из 750: Sol / Astra |")
    print("|---|---|---|")
    for slug, j in out["judges"].items():
        print(f"| {ev[slug]['name']} | {j['agree']:.1%} | {j['sol_on']} / {j['astra_on']} |")
    js = [j for j in out["judges"].values() if "fable_on" in j]
    if js:
        print("\n| Событие | совпадение: Sol–Astra / Sol–Fable / Astra–Fable | все трое согласны | "
              "«да» из 750: Sol / Astra / Fable / большинство |")
        print("|---|---|---|---|")
        for slug, j in out["judges"].items():
            if "fable_on" in j:
                print(f"| {ev[slug]['name']} | {j['agree']:.1%} / {j['agree_sol_fable']:.1%} / "
                      f"{j['agree_astra_fable']:.1%} | {j['unanimous']:.1%} | "
                      f"{j['sol_on']} / {j['astra_on']} / {j['fable_on']} / {j['majority_on']} |")
    for ref, title in (("astra", "эталон Astra"), ("agreed", "только посты, где Sol и Astra согласны"),
                       ("majority", "эталон — большинство Sol, Astra и Fable")):
        per = out["by_reference"][ref]
        if not per:
            continue
        cols = [w for w in ["reference", "codex", "astra"] + READERS[1:] if all(w in r for r in per.values())]
        lab = {**names, "reference": "сам эталон", "codex": "Sol (Codex)", "astra": "Astra"}
        print(f"\nF1 по выборке, {title}:\n")
        print("| Событие | " + " | ".join(lab[w] for w in cols) + " |")
        print("|---|" + "---|" * len(cols))
        for slug, r in per.items():
            print(f"| {ev[slug]['name']} | " + " | ".join(f"{r[w]['f1']:.3f}" for w in cols) + " |")
        print("| среднее отставание от эталона | " + " | ".join(
            f"{np.mean([r[w]['f1'] - r['reference']['f1'] for r in per.values()]):+.3f}" for w in cols) + " |")


if __name__ == "__main__":
    main()
