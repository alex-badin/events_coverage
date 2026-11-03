#!/usr/bin/env python
"""Can the Decisions API step cost half as much without losing quality? (03.11, the $4 Decisions test budget)

Variants of the request, each rescored on the 750 labelled posts of the ten events and measured
against the majority of Sol, Astra and Fable (F1 at the Luna sample cut-off, as in report.py):
  layout "old"     the run of 03.11: shared input = the event block, and every question repeats the
                   yes/no question and its criteria before the post;
  layout "shared"  the question and criteria go once into the shared input; a question is only the post.
  chars            first N characters of each post (2,500 in every earlier run).
  layout "choice"  as "shared", but each post is a `choice` question with values yes / no instead of a
                   `predicate`; the score is the probability of "yes". A choice question carries about
                   98 tokens of fixed overhead, a predicate about 145 (probes).
  per_request      questions per request (50 before; the API takes up to 400).
Checks on the 3,000 candidates per event: repeated texts (free), stopping in similarity order (all
3,000 scored once with variant shared_600, then the stop rules are replayed on those scores).

    python decisions_cost.py probe             # 4 requests that split the billed tokens (~$0.01)
    python decisions_cost.py run <name>        # rescore the 7,500 labelled posts with a variant
    python decisions_cost.py candidates        # score all 3,000 candidates per event, variant shared_600
    python decisions_cost.py report            # tables -> decisions_cost.json
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import report as RP
import steps as S
import ten as T

V = RP.V
CAP = 3.72                 # what is left of Alex's $4 budget for the Decisions test
WORK = T.OUT / "decisions_cost"
VARIANTS = {               # name: (layout, chars, questions per request)
    "old": ("old", 2500, 50),
    "shared": ("shared", 2500, 50),
    "shared_1000": ("shared", 1000, 50),
    "shared_600": ("shared", 600, 50),
    "choice_600": ("choice", 600, 50),
    "choice_400": ("choice", 400, 50),
    "choice_400_again": ("choice", 400, 50),      # the same variant once more: how much F1 moves between runs
    "choice_400_x400": ("choice", 400, 400),
}


def spent():
    return sum(json.loads(line)["usd"] for line in open(T.LEDGER) if '"decisions_cost' in line)


def body(slug, ids, layout, chars):
    q, posts = T.question(slug), T.posts(slug)
    ask = f"Answer true if: {q['criteria']['true']} Answer false if: {q['criteria']['false']}"
    if layout == "old":
        shared = json.dumps(q["instructions"], ensure_ascii=False)
        head = f"{q['instructions']['question']} {ask}\n\nNews post:\n"
    else:
        shared = json.dumps({**q["instructions"], "answer": ask}, ensure_ascii=False)
        head = "News post:\n"
    qs = [{"type": "predicate", "name": f"p{i}", "instructions": head + posts[i]["text"][:chars]} for i in ids]
    if layout == "choice":
        for qn in qs:
            qn["type"], qn["choices"] = "choice", [{"value": "yes"}, {"value": "no"}]
    return {"model": "gpt-6-luna", "input": shared, "questions": qs}


def call(client, b):
    d = client.post("/decisions", body=b, cast_to=object)
    def p(a):   # predicate: probability; choice: the probability of "yes"
        if a.get("probabilities"):
            return next(x["probability"] for x in a["probabilities"] if x["value"] == "yes")
        return a.get("probability")
    return ({a["name"][1:]: round(float(p(a)), 4) for a in d["answers"] if p(a) is not None},
            d.get("usage") or {})


def score(name, slug, ids, target):
    """Score ids with variant name; saved after every request, so a crash loses no billed call."""
    layout, chars, per = VARIANTS[name]
    have = json.loads(target.read_text()) if target.exists() else {"p": {}, "usage": []}
    todo = [i for i in ids if str(i) not in have["p"]]
    client = S._openai()
    chunks = [todo[k:k + per] for k in range(0, len(todo), per)]
    usd = 0.0
    with ThreadPoolExecutor(4) as pool:
        for p, u in pool.map(lambda c: call(client, body(slug, c, layout, chars)), chunks):
            have["p"].update(p)
            have["usage"].append(u)
            usd += u.get("input_tokens", 0) * S.DEC_PRICE_PER_M / 1e6
            target.write_text(json.dumps(have))
    if usd:
        T.book("decisions_cost", usd, slug=slug, variant=name, model="gpt-6-luna /v1/decisions",
               input_tokens=sum(u.get("input_tokens", 0) for u in have["usage"]))
    return usd


def run(name, candidates=False):
    for slug in T.EVENTS:
        if spent() > CAP:
            raise SystemExit(f"stopping: ${spent():.3f} of the ${CAP} cap")
        ids = T.ranked(slug) if candidates else sorted(T.labels(slug)[0])
        folder = WORK / (f"{name}_candidates" if candidates else name)
        folder.mkdir(parents=True, exist_ok=True)
        if candidates and not (folder / f"{slug}.json").exists() and (WORK / name / f"{slug}.json").exists():
            (folder / f"{slug}.json").write_text((WORK / name / f"{slug}.json").read_text())   # labelled posts already scored
        usd = score(name, slug, ids, folder / f"{slug}.json")
        print(f"{slug}: ${usd:.4f}; spent ${spent():.3f}", flush=True)


def probe():
    """Billed tokens of one 50-question request of crocus in four shapes."""
    slug = "crocus_attack_2024w13"
    ids = sorted(T.labels(slug)[0])[:50]
    client = S._openai()
    out = {}
    shapes = {"old": body(slug, ids, "old", 2500), "shared": body(slug, ids, "shared", 2500)}
    empty = body(slug, ids, "old", 0)                     # question + criteria, no post text
    bare = body(slug, ids, "old", 0)
    for qn in bare["questions"]:
        qn["instructions"] = "x"                          # what a question costs by itself
    one = body(slug, ids[:1], "old", 0)
    one["questions"][0]["instructions"] = "x"             # the shared input alone, plus one bare question
    shapes |= {"no_post_text": empty, "bare_questions": bare, "one_bare_question": one}
    for k, b in shapes.items():
        _, u = call(client, b)
        out[k] = u.get("input_tokens", 0)
        T.book("decisions_cost", out[k] * S.DEC_PRICE_PER_M / 1e6, step_detail=f"probe {k}", model="gpt-6-luna /v1/decisions")
    (WORK / "probe.json").write_text(json.dumps(out, indent=2))
    print(out)


def evaluate(s, slug):
    """AUC, best F1 and F1 at the Luna sample cut, against the majority of Sol, Astra and Fable."""
    maj, (_, weight) = RP.majority(slug), T.labels(slug)
    ids = sorted(maj)
    s = {i: s.get(i, 0.0) for i in ids}
    luna = json.loads((T.OUT / "reader_labels" / "gpt-6-luna" / f"{slug}.json").read_text())["labels"]
    lab = {**maj, **{int(k): v for k, v in luna.items() if int(k) in maj}}
    rng = np.random.default_rng(17)
    res = [V.counts(ids, maj, weight, s, V.sample_cut(ids, maj, weight, s, RP.N, rng, lab)) for _ in range(V.SEEDS)]
    return {"auc": V.auc(ids, maj, weight, s), "best": V.counts(ids, maj, weight, s, V.best_cut(ids, maj, weight, s))["f1"],
            **{k: float(np.mean([x[k] for x in res])) for k in ("f1", "lost", "extra")}}


def load(folder, slug):
    p = WORK / folder / f"{slug}.json"
    if folder == "old" and not p.exists():                 # the 03.11 run is variant "old"
        p = T.OUT / "decisions" / f"{slug}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return {int(k): v for k, v in d["p"].items()}, sum(u.get("input_tokens", 0) for u in d["usage"]), len(d["p"])


def duplicates(slug):
    """Share of the 3,000 candidates whose cleaned text (first 2,500 chars, spaces squeezed) repeats
    an earlier candidate's."""
    posts, seen, rep = T.posts(slug), set(), 0
    for i in T.ranked(slug):
        t = " ".join(posts[i]["text"][:2500].split()).lower()
        rep += t in seen
        seen.add(t)
    return rep / 3000


def stop_rule(s_all, slug, batch, floor):
    """Score candidates in similarity order, batch by batch; stop after the first batch where fewer than
    `floor` of the posts score >= 0.5. Returns the ranks scored and the scores with the rest at 0."""
    order = T.ranked(slug)
    for k in range(0, len(order), batch):
        part = order[k:k + batch]
        if np.mean([s_all.get(i, 0) >= 0.5 for i in part]) < floor:
            n = k + batch
            break
    else:
        n = len(order)
    kept = set(order[:n])
    return n, {i: v for i, v in s_all.items() if i in kept}


def report():
    out = {"probe": json.loads((WORK / "probe.json").read_text()) if (WORK / "probe.json").exists() else None,
           "variants": {}, "duplicates": {}, "stop": {}}
    for name in VARIANTS:
        rows = {}
        for slug in T.EVENTS:
            got = load(name, slug)
            if got is None:
                break
            s, tok, n = got
            rows[slug] = {"tokens_per_post": tok / n, **evaluate(s, slug)}
        if len(rows) == len(T.EVENTS):
            out["variants"][name] = rows
    for slug in T.EVENTS:
        out["duplicates"][slug] = duplicates(slug)
    best = [n for n in VARIANTS if n in out["variants"]][-1] if out["variants"] else None
    cand = {slug: load("shared_600_candidates", slug) for slug in T.EVENTS}
    if all(cand.values()):
        for batch, floor in ((250, 0.05), (500, 0.05), (500, 0.02), (250, 0.10)):
            rows = {}
            for slug in T.EVENTS:
                s_all = cand[slug][0]
                n, s = stop_rule(s_all, slug, batch, floor)
                rows[slug] = {"scored": n, **evaluate(s, slug), "full": evaluate(s_all, slug)}
            out["stop"][f"{batch}_{floor}"] = rows
    (T.HERE / "decisions_cost.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    show(out)


def show(out):
    ev = T.SHORT
    if out["probe"]:
        print("probe (input tokens of one 50-question crocus request):", out["probe"])
    names = list(out["variants"])
    base = out["variants"].get("old")
    print("\n| Variant | tokens per post | saving vs old | AUC | F1 best | F1 Luna cut | F1 change |")
    print("|---|---|---|---|---|---|---|")
    for n in names:
        r = out["variants"][n]
        tok = np.mean([x["tokens_per_post"] for x in r.values()])
        f1 = np.mean([x["f1"] for x in r.values()])
        b_tok = np.mean([x["tokens_per_post"] for x in base.values()]) if base else tok
        b_f1 = np.mean([x["f1"] for x in base.values()]) if base else f1
        print(f"| {n} | {tok:.0f} | {1 - tok / b_tok:.0%} | {np.mean([x['auc'] for x in r.values()]):.3f} | "
              f"{np.mean([x['best'] for x in r.values()]):.3f} | {f1:.3f} | {f1 - b_f1:+.3f} |")
    if names:
        print("\n| Event | " + " | ".join(f"F1 {n}" for n in names) + " |")
        print("|---|" + "---|" * len(names))
        for slug in T.EVENTS:
            print(f"| {ev[slug]} | " + " | ".join(f"{out['variants'][n][slug]['f1']:.3f}" for n in names) + " |")
    print("\nrepeated texts among the 3,000 candidates:",
          ", ".join(f"{ev[s].split(',')[0]} {v:.1%}" for s, v in out["duplicates"].items()),
          f"; mean {np.mean(list(out['duplicates'].values())):.1%}")
    for rule, rows in out["stop"].items():
        sc = np.mean([r["scored"] for r in rows.values()])
        df = np.mean([r["f1"] - r["full"]["f1"] for r in rows.values()])
        print(f"\nstop rule {rule}: scored {sc:.0f} of 3,000 on average ({1 - sc / 3000:.0%} saved); F1 change {df:+.4f}")
        print("| Event | scored | F1 full | F1 with stop |")
        print("|---|---|---|---|")
        for slug, r in rows.items():
            print(f"| {ev[slug]} | {r['scored']} | {r['full']['f1']:.3f} | {r['f1']:.3f} |")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "probe":
        probe()
    elif cmd == "run":
        run(sys.argv[2])
    elif cmd == "candidates":
        run("shared_600", candidates=True)
    else:
        report()
