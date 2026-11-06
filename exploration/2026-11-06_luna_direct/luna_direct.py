#!/usr/bin/env python
"""Label every candidate of the events after 2026-W20 directly with gpt-6-luna through Codex (subscription,
no API spend): yes/no, no probability and no cut-off. Same prompt and slices as the ten-event reader test
(run.PROMPT, no event brief, 2,500 characters, 50 posts per call, effort low). Slices are shuffled so that a
call does not hold only the closest or only the farthest candidates. Each answer is saved as it arrives;
a rerun skips what is saved.

    python luna_direct.py run N [--scored K] [--workers W]   # first N unscored events by date, K already scored
    python luna_direct.py report                             # per event: answered, yes, overlap with Decisions

Account: CODEX_CLI (default codex-secondary).
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-11-03_new_weeks"))
import new_weeks as N  # noqa: E402

R = N.R
OUT = N.ROOT / "data" / "interim" / "luna_direct"
SLICE, CHARS, SEED = 50, 2500, 17
MODEL, EFFORT = "gpt-6-luna", "low"
CLI = os.environ.get("CODEX_CLI", "codex-secondary")
SCHEMA = R.OUT / "labels" / "schema.json"
LIMIT_WORDS = ("usage limit", "rate limit", "rate_limit", "quota", "too many requests")
stop = threading.Event()
log_lock = threading.Lock()


def queue():
    """The events the run left out, in date order: 213 unscored, 13 scored but held back."""
    ev = [e for e in N.events() if e["year"] * 100 + e["week"] > N.LAST_COMPLETE_WEEK]
    return ev


def slices(e):
    ids = [c["i"] for c in N.candidates(e)]
    random.Random(SEED).shuffle(ids)
    return [ids[k:k + SLICE] for k in range(0, len(ids), SLICE)]


def log(**row):
    with log_lock, (OUT / "calls.jsonl").open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "cli": CLI, **row}, ensure_ascii=False) + "\n")


def one(job):
    e, k, ids = job
    target = OUT / e["id"] / f"slice_{k:03d}.json"
    if target.exists() or stop.is_set():
        return
    ps = N.posts()
    block = "\n\n".join(f"[id {i}] {ps[i]['text'][:CHARS]}" for i in ids)
    text = R.PROMPT.format(week=f"{e['year']}-W{e['week']:02d}", name=e["name"], quotes="; ".join(e["quotes"]),
                           lo=e["window"][0], hi=e["window"][1], posts=block)
    for attempt in range(3):
        if stop.is_set():
            return
        started = time.time()
        with tempfile.TemporaryDirectory() as work:
            answer = Path(work) / "a.json"
            r = subprocess.run([CLI, "exec", "--json", "--skip-git-repo-check", "-C", work, "-s", "read-only", "--ephemeral",
                                "-m", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"',
                                "--output-schema", str(SCHEMA), "-o", str(answer), "-"],
                               input=text, capture_output=True, text=True, timeout=600)
            got = answer.read_text() if answer.exists() else ""
        seconds = round(time.time() - started, 1)
        usage = limits = None
        for line in r.stdout.splitlines():
            if '"usage"' in line:
                try:
                    usage = json.loads(line).get("usage") or usage
                except json.JSONDecodeError:
                    pass
        try:
            labels = {int(str(x["id"]).strip()): x["label"] == "yes" for x in json.loads(got)["labels"]
                      if str(x["id"]).strip().isdigit()}
            labels = {i: v for i, v in labels.items() if i in set(ids)}
        except (json.JSONDecodeError, KeyError):
            labels = {}
        ok = len(labels) >= 0.95 * len(ids)
        log(event=e["id"], slice=k, attempt=attempt, ok=ok, answered=len(labels), asked=len(ids), seconds=seconds, usage=usage,
            rc=r.returncode, err="" if ok else (r.stderr + r.stdout)[-300:])
        if ok:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"model": MODEL, "effort": EFFORT, "cli": CLI, "date": time.strftime("%Y-%m-%d"),
                                          "asked": ids, "labels": {str(i): v for i, v in labels.items()}}))
            return
        if any(w in (r.stderr + r.stdout).lower() for w in LIMIT_WORDS):
            stop.set()
            print("limit reached; stopping", flush=True)
            return
        time.sleep(5)


def run(n, scored, workers):
    ev = queue()
    fresh = [e for e in ev if N.scores(e) is None][:n]
    held = [e for e in ev if N.scores(e) is not None][:scored]
    jobs = [(e, k, ids) for e in held + fresh for k, ids in enumerate(slices(e))]
    print(f"{len(held) + len(fresh)} events, {len(jobs)} calls, {workers} at a time, {CLI}", flush=True)
    N.posts()
    started = time.time()
    done = [0]

    def wrapped(job):
        one(job)
        done[0] += 1
        if done[0] % 20 == 0:
            print(f"{done[0]}/{len(jobs)} in {time.time() - started:.0f}s", flush=True)

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        list(pool.map(wrapped, jobs))
    print(f"finished in {time.time() - started:.0f}s", flush=True)


def report():
    for e in queue():
        folder = OUT / e["id"]
        if not folder.exists():
            continue
        labels = {}
        for p in folder.glob("slice_*.json"):
            labels.update({int(k): v for k, v in json.loads(p.read_text())["labels"].items()})
        line = f"{e['year']}-W{e['week']:02d} {e['name'][:50]} | {e['percentage']}% | answered {len(labels)} | yes {sum(labels.values())}"
        s, lp = N.scores(e), N.OUT / "luna" / f"{e['id']}.json"
        if s is not None and lp.exists():
            cut = json.loads(lp.read_text())["cut"]
            kept = {i for i in s if s[i] >= cut}
            yes = {i for i, v in labels.items() if v}
            both = [i for i in labels if i in s]
            kept_here = kept & set(both)
            line += (f" | Decisions kept {len(kept_here)} of the same {len(both)} (cut {cut}) | both yes {len(yes & kept_here)}"
                     f" | same answer {sum((i in yes) == (i in kept_here) for i in both)}")
        print(line)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "report":
        report()
    else:
        opt = lambda name, d: int(a[a.index(name) + 1]) if name in a else d
        run(int(a[1]), opt("--scored", 0), opt("--workers", 8))
