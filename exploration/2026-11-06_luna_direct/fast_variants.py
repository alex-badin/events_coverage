#!/usr/bin/env python
"""Fewer calls per event: the same score prompt with shorter posts and more posts per call, on the ten control
events' 750 labelled posts. Decides the format for the rest of the run and the 2,780 events of the history."""
import json, random, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-10-26_ten_events_readers"))
import report as RP, ten as T, decisions_cost as D, steps  # noqa: E402
R = steps.R if hasattr(steps, "R") else None
S = HERE.parents[1] / "data" / "interim" / "luna_direct"
TAIL = re.search(r'TAIL = """\n(.*?)"""', (HERE / "luna_scores.py").read_text(), re.S).group(0)[len('TAIL = """'):-3]
PROMPTS = S.parent / "ten_events_readers" / "reader_labelling" / "prompts"
VARIANTS = {"c400_n200": (400, 200), "c1000_n100": (1000, 100)}


def head(slug):
    """Everything before the posts in the stored prompt, so the wording stays byte-equal."""
    text = next(iter(sorted(PROMPTS.glob(f"{slug}_*.txt")))).read_text()
    return text[:text.index("[id ")]


def one(job):
    v, slug, k, ids, text = job
    o = S / "variants" / v / f"{slug}_{k:03d}.json"
    if o.exists() and o.stat().st_size:
        return
    o.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as w:
        subprocess.run(["codex-secondary", "exec", "--ignore-user-config", "--skip-git-repo-check", "-C", w, "-s", "read-only", "--ephemeral", "-m", "gpt-6-luna",
                        "-c", 'model_reasoning_effort="low"', "--output-schema", str(S / "score_schema.json"), "-o", str(o), "-"],
                       input=text, capture_output=True, text=True, timeout=900)


jobs = []
for v, (chars, n) in VARIANTS.items():
    for slug in T.EVENTS:
        maj = RP.majority(slug)
        posts = T.posts(slug)
        ids = sorted(maj)
        random.Random(17).shuffle(ids)
        for k in range(0, len(ids), n):
            chunk = ids[k:k + n]
            block = "\n\n".join(f"[id {i}] {posts[i]['text'][:chars]}" for i in chunk)
            jobs.append((v, slug, k // n, chunk, head(slug) + block + "\n" + TAIL))
print(len(jobs), "calls", flush=True)
with ThreadPoolExecutor(10) as pool:
    list(pool.map(one, jobs))
rows = {v: [] for v in VARIANTS}
print("event | c400_n200 F1, answered | c1000_n100 F1, answered | score 2500/50 | Decisions")
base = {}
for line in (S / "score_variant.txt").read_text().splitlines():
    m = re.match(r"(\w+) \| \d+ scored: [\d.]+, [\d.]+, ([\d.]+)", line)
    if m:
        base[m.group(1)] = float(m.group(2))
for slug in T.EVENTS:
    cols = []
    for v in VARIANTS:
        s = {}
        for p in (S / "variants" / v).glob(f"{slug}_*.json"):
            if p.stat().st_size:
                s.update({int(x["id"]): x["score"] / 100 for x in json.loads(p.read_text())["scores"] if str(x["id"]).isdigit()})
        e = D.evaluate(s, slug)
        rows[v].append(e["f1"])
        cols.append(f"{e['f1']:.3f}, {len(s)}")
    print(slug, "|", " | ".join(cols), "|", base.get(slug), "|", f"{D.evaluate(D.load('choice_400_x400', slug)[0], slug)['f1']:.3f}")
print("mean", {v: round(float(np.mean(x)), 3) for v, x in rows.items()})
