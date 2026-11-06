#!/usr/bin/env python
"""Score every candidate of the events after 2026-W20 with gpt-6-luna through Codex (subscription, no API spend):
0-100 per post in place of the Decisions API probability; the per-event cut-off comes later, as before.
run.PROMPT plus TAIL (score_variant.py), no event brief, 1,000 characters, 100 posts per call in shuffled order,
effort low. Events in date order, so an interrupted run leaves whole weeks. Each answer is saved as it arrives;
a rerun skips what is saved. Stops when the account reaches its limit or the cap below.

    python luna_scores.py prepare                             # once: prompts to disk
    CODEX_CLI=codex-secondary python luna_scores.py run [--workers W]
    python luna_scores.py status
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import random
import re
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
OUT = N.ROOT / "data" / "interim" / "luna_direct" / "scores"
SCHEMA = OUT.parent / "score_schema.json"
PROMPTS = OUT.parent / "score_prompts_1000"
SLICE, CHARS, SEED = 100, 1000, 17     # fast_variants.py: mean F1 0.940, 2,500/50 0.938, Decisions 0.927
OLD_SLICE, OLD_CHARS = 50, 2500
MODEL, EFFORT = "gpt-6-luna", "low"
TAIL = """
Дополнительно: вместо метки дай каждому посту score — целое число от 0 до 100, насколько вероятно, что правильный ответ "yes".
Используй всю шкалу: 0 — точно о другом, 100 — точно об этом событии, средние значения для пограничных и косвенных постов."""
CLI = os.environ.get("CODEX_CLI", "codex-secondary")
HOME = {"codex-secondary": "~/.codex-secondary", "codex": "~/.codex"}[CLI]
WEEK_CAP = {"codex-secondary": 95.0, "codex": 98.0}[CLI]
LIMIT_WORDS = ("usage limit", "rate limit", "rate_limit", "quota", "too many requests")
stop = threading.Event()
lock = threading.Lock()


def queue():
    return [e for e in N.events() if e["year"] * 100 + e["week"] > N.LAST_COMPLETE_WEEK]


def fmt(e):
    """Events begun before the switch of 2026-11-06 keep 2,500 characters and 50 posts per call."""
    for p in (OUT / e["id"]).glob("slice_*.json") if (OUT / e["id"]).exists() else []:
        if len(json.loads(p.read_text())["asked"]) <= OLD_SLICE:
            return OLD_CHARS, OLD_SLICE, OUT.parent / "score_prompts"
    return CHARS, SLICE, PROMPTS


def slices(e):
    ids = [c["i"] for c in N.candidates(e)]
    random.Random(SEED).shuffle(ids)
    size = fmt(e)[1]
    return [ids[k:k + size] for k in range(0, len(ids), size)]


def prepare():
    """The prompts on disk, so the run itself does not hold the 1.5 GB post file in memory (it did, twice, in swap)."""
    ps = N.posts()
    for e in queue():
        if fmt(e)[1] == OLD_SLICE:
            continue
        (PROMPTS / e["id"]).mkdir(parents=True, exist_ok=True)
        for k, ids in enumerate(slices(e)):
            block = "\n\n".join(f"[id {i}] {ps[i]['text'][:CHARS]}" for i in ids)
            (PROMPTS / e["id"] / f"slice_{k:03d}.txt").write_text(R.PROMPT.format(
                week=f"{e['year']}-W{e['week']:02d}", name=e["name"], quotes="; ".join(e["quotes"]),
                lo=e["window"][0], hi=e["window"][1], posts=block) + TAIL)
    print("prompts written")


def log(**row):
    with lock, (OUT.parent / "score_calls.jsonl").open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "cli": CLI, **row}, ensure_ascii=False) + "\n")


def limits_used():
    """(window %, week %) from a one-word call. A window-only reading is what stops the run early."""
    out = subprocess.run(["zsh", str(HERE / "limits.sh"), CLI, os.path.expanduser(HOME)], capture_output=True, text=True, timeout=120).stdout
    nums = re.findall(r"'used_percent': ([\d.]+)", out)
    if not nums:
        return None
    return float(nums[0]), float(nums[-1])


def claim(target):
    """Both accounts run at once over the same queue: a claim file keeps them off the same slice. A claim older
    than 15 minutes belonged to a call that died."""
    path = target.with_suffix(".claim")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime > 900:
        path.unlink(missing_ok=True)
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL))
        return True
    except FileExistsError:
        return False


def one(job):
    e, k, ids = job
    target = OUT / e["id"] / f"slice_{k:03d}.json"
    if target.exists() or stop.is_set() or not claim(target):
        return
    text = (fmt(e)[2] / e["id"] / f"slice_{k:03d}.txt").read_text()
    for attempt in range(3):
        if stop.is_set():
            return
        started = time.time()
        with tempfile.TemporaryDirectory() as work:
            answer = Path(work) / "a.json"
            try:
                r = subprocess.run([CLI, "exec", "--ignore-user-config", "--json", "--skip-git-repo-check", "-C", work, "-s", "read-only", "--ephemeral",
                                    "-m", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"', "--output-schema", str(SCHEMA),
                                    "-o", str(answer), "-"], input=text, capture_output=True, text=True, timeout=600)
            except subprocess.TimeoutExpired:
                log(event=e["id"], slice=k, attempt=attempt, ok=False, err="timeout")
                continue
            got = answer.read_text() if answer.exists() else ""
        usage = None
        for line in r.stdout.splitlines():
            if '"usage"' in line:
                try:
                    usage = json.loads(line).get("usage") or usage
                except json.JSONDecodeError:
                    pass
        try:
            have = {int(str(x["id"]).strip()): int(x["score"]) for x in json.loads(got)["scores"] if str(x["id"]).strip().isdigit()}
            have = {i: max(0, min(100, v)) for i, v in have.items() if i in set(ids)}
        except (json.JSONDecodeError, KeyError, ValueError):
            have = {}
        ok = len(have) >= 0.95 * len(ids)
        tail = (r.stderr + r.stdout)[-300:]
        log(event=e["id"], slice=k, attempt=attempt, ok=ok, answered=len(have), asked=len(ids), seconds=round(time.time() - started, 1),
            usage=usage, rc=r.returncode, err="" if ok else tail)
        if ok:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"model": MODEL, "effort": EFFORT, "cli": CLI, "date": time.strftime("%Y-%m-%d"),
                                          "asked": ids, "scores": {str(i): v for i, v in have.items()}}))
            return
        if any(w in tail.lower() for w in LIMIT_WORDS):
            stop.set()
            target.with_suffix(".claim").unlink(missing_ok=True)
            print("limit reached", flush=True)
            return
        time.sleep(5)
    target.with_suffix(".claim").unlink(missing_ok=True)


def run(workers):
    jobs = [(e, k, ids) for e in queue() for k, ids in enumerate(slices(e)) if not (OUT / e["id"] / f"slice_{k:03d}.json").exists()]
    print(f"{time.strftime('%H:%M')} {len(jobs)} calls to go, {workers} at a time, {CLI}", flush=True)
    done = [0]

    def wrapped(job):
        one(job)
        done[0] += 1
        if done[0] % 100 == 0 and not stop.is_set():
            used = limits_used()
            print(f"{time.strftime('%H:%M')} {done[0]}/{len(jobs)}; used window, week: {used}", flush=True)
            if used and (used[0] >= 98.0 or used[1] >= WEEK_CAP):
                stop.set()

    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        list(pool.map(wrapped, jobs))
    print(f"{time.strftime('%H:%M')} stopped after {done[0]}; stop={stop.is_set()}", flush=True)
    sys.exit(0 if not stop.is_set() and done[0] == len(jobs) else 3)


def status():
    print(time.strftime("%H:%M"), end=" ")
    full = part = 0
    weeks = {}
    for e in queue():
        n = sum(1 for _ in (OUT / e["id"]).glob("slice_*.json")) if (OUT / e["id"]).exists() else 0
        need = len(slices(e))
        full += n == need
        part += 0 < n < need
        w = f"{e['year']}-W{e['week']:02d}"
        weeks.setdefault(w, []).append(n == need)
    closed = [w for w, v in weeks.items() if all(v)]
    print(f"{full} of {len(queue())} events complete, {part} in progress; {len(closed)} of {len(weeks)} weeks complete: {closed[:1]}..{closed[-1:]}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "status":
        status()
    elif a[0] == "prepare":
        prepare()
    else:
        run(int(a[a.index("--workers") + 1]) if "--workers" in a else 16)
