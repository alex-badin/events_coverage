#!/usr/bin/env python
"""From Luna scores to the files the warehouse loads, the same steps as new_weeks.py: 100-post sample from ten
score bands, read by Sol through Codex, cut-off by evaluate.best_cut, then one dataset CSV and manifest per event.

    python luna_finish.py prompts
    zsh ../2026-10-17_jev_selection/codex_answer.sh ../../data/interim/luna_direct/cutoffs
    python luna_finish.py collect
    python luna_finish.py export        # whole weeks only; writes data/processed and configs/new_weeks_events.json
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-11-03_new_weeks"))
import new_weeks as N  # noqa: E402

R, V = N.R, N.V
BASE = N.ROOT / "data" / "interim" / "luna_direct"
SCORES, CUTS, ANSWERS = BASE / "scores", BASE / "cuts", BASE / "cutoffs"
READER = "gpt-6.1-sol, Codex subscription, effort medium"
SCORER = "gpt-6-luna via Codex, score 0-100 divided by 100, effort low, no brief"


def luna_scores(e):
    """Saved scores on the 0-1 scale of the Decisions probability; None until every slice of the event is saved."""
    folder = SCORES / e["id"]
    files = list(folder.glob("slice_*.json")) if folder.exists() else []
    if not files or sum(len(json.loads(p.read_text())["asked"]) for p in files) < len(N.candidates(e)):
        return None
    s = {}
    for p in files:
        s.update({int(k): v / 100 for k, v in json.loads(p.read_text())["scores"].items()})
    return s


N.scores = luna_scores      # new_weeks.sample() and complete() now read these instead of the Decisions files
N.MAX_UNANSWERED = 150      # 95% of a slice is accepted, so up to 5% of an event may lack a score


def len_show(e):
    first = next((SCORES / e["id"]).glob("slice_*.json"))
    return 2500 if len(json.loads(first.read_text())["asked"]) <= 50 else 1000


def queue():
    return [e for e in N.events() if e["year"] * 100 + e["week"] > N.LAST_COMPLETE_WEEK]


def prompts():
    ps = N.posts()
    folder = ANSWERS / "prompts"
    folder.mkdir(parents=True, exist_ok=True)
    (ANSWERS / "schema.json").write_text((R.OUT / "labels" / "schema.json").read_text())
    n = 0
    for e in queue():
        if (CUTS / f"{e['id']}.json").exists() or (folder / f"{e['id']}.txt").exists() or luna_scores(e) is None:
            continue
        picked, _ = N.sample(e)
        block = "\n\n".join(f"[id {i}] {ps[i]['text'][:2500]}" for i in picked)
        (folder / f"{e['id']}.txt").write_text(R.PROMPT.format(
            week=f"{e['year']}-W{e['week']:02d}", name=e["name"], quotes="; ".join(e["quotes"]),
            lo=e["window"][0], hi=e["window"][1], posts=block), encoding="utf-8")
        n += 1
    print(f"{n} prompts")


def collect():
    CUTS.mkdir(exist_ok=True)
    n = 0
    for e in queue():
        target, answer = CUTS / f"{e['id']}.json", ANSWERS / "out" / f"{e['id']}.json"
        if target.exists() or not answer.exists():
            continue
        picked, w = N.sample(e)
        labels = {int(str(x["id"]).strip()): x["label"] == "yes" for x in json.loads(answer.read_text())["labels"]
                  if str(x["id"]).strip().isdigit()}
        got = [i for i in picked if i in labels]
        if len(got) < 0.95 * len(picked):
            print(f"{e['id']}: answer covers {len(got)} of {len(picked)}; rerun"); answer.unlink()
            continue
        s = luna_scores(e)
        cut = V.best_cut(got, labels, w, s) if any(labels[i] for i in got) else 1.01
        target.write_text(json.dumps({"labels": {str(i): labels[i] for i in got}, "weights": {str(i): w[i] for i in got},
                                      "missing": [i for i in picked if i not in labels], "cut": cut, "reader": READER}))
        cands = N.candidates(e)
        print(f"{e['year']}-W{e['week']:02d} {e['name'][:50]}: cut {cut}, kept {sum(s.get(c['i'], 0) >= cut for c in cands)} of {len(cands)}, "
              f"sample yes {sum(labels[i] for i in got)} of {len(got)}")
        n += 1
    print(f"{n} cut-offs")


def export():
    ps = N.posts()
    out_dir = N.ROOT / "data" / "processed"
    weeks = {}
    for e in queue():
        weeks.setdefault((e["year"], e["week"]), []).append(e)
    whole = sorted(k for k, v in weeks.items() if all((CUTS / f"{e['id']}.json").exists() for e in v))
    # weeks must run on from 2026-W20 without a hole: one missing week would look like a week without events
    config_path = N.ROOT / "configs" / "new_weeks_events.json"
    config = json.loads(config_path.read_text())
    table = []
    for key in whole:
        for e in weeks[key]:
            cj, s = json.loads((CUTS / f"{e['id']}.json").read_text()), luna_scores(e)
            cos = {c["i"]: c["cos"] for c in N.candidates(e)}
            cut = cj["cut"]
            kept = [i for i in cos if i in s and s[i] >= cut]
            slug = f"event_{e['id']}_fulltext"
            for name in ("with_posts", "empty"):
                if slug in config[name]:
                    config[name].remove(slug)
            config["with_posts" if kept else "empty"].append(slug)
            if kept:
                with (out_dir / f"{slug}_dataset.csv").open("w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["source", "message_id", "date", "is_digest", "summary", "original_message", "views",
                                "forwards", "cosine_max", "rerank_score", "keyword_match"])
                    for i in sorted(kept, key=lambda i: -s[i]):
                        p = ps[i]
                        w.writerow([p["source"], p["message_id"], p["date"], "", "", p["text"], p["views"] or "", "", cos[i], s[i], ""])
            sc = json.loads((N.OUT / "scores" / f"{e['id']}.json").read_text())
            (out_dir / f"{slug}_manifest.json").write_text(json.dumps({
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "event": {"name": e["name"], "year": e["year"], "week": e["week"], "fom_percentage": e["percentage"],
                          "quotes": e["quotes"], "event_id": e["id"]},
                "window": {"match_start": e["window"][0], "match_end_exclusive": e["window"][1]},
                "models": {"retriever": "qwen3_fulltext", "embed_model": N.M.QWEN_MODEL, "rerank_model": SCORER,
                           "cut_reader": cj["reader"], "brief": "not used"},
                "params": {"top_k": N.TOP_K, "rerank_threshold": cut, "show_chars": len_show(e)},
                "counts": {"candidates": len(cos), "scored": sum(i in s for i in cos), "kept": len(kept),
                           "embedded_pool": sc["window_posts_with_text"], "window_posts": sc["window_posts"]}},
                ensure_ascii=False, indent=1))
            table.append([e["id"], f"{e['year']}-W{e['week']:02d}", e["name"], e["percentage"], cj["reader"], cut,
                          sum(i in s for i in cos), len(kept), len(cj["labels"]), sum(cj["labels"].values()), len(cj["missing"])])
    config_path.write_text(json.dumps(config, indent=0) + "\n")
    with (HERE / "cutoffs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "week", "event", "fom_percentage", "cut_reader", "cut", "scored_candidates", "kept_posts",
                    "sample_labelled", "sample_yes", "sample_missing"])
        w.writerows(table)
    print(f"{len(whole)} whole weeks, {len(table)} events exported")


if __name__ == "__main__":
    {"prompts": prompts, "collect": collect, "export": export}[sys.argv[1]]()
