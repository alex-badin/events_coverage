#!/usr/bin/env python
"""Luna 0-100 scores for the 2,780 events before 2025-W12, the format of luna_scores.py (1,000 characters,
100 posts per call, shuffled, effort low, no brief). Newest events first. Candidates come from
data/interim/history/candidates (month, line in that month's texts file).

    python history_scores.py prepare           # prompts to disk, events newest first
    CODEX_CLI=codex-secondary python history_scores.py run --workers 12 [--until EPOCH]
    python history_scores.py status
"""
import glob, json, os, random, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.argv_saved = list(sys.argv); sys.argv = sys.argv[:1]
import luna_scores as L  # noqa: E402
sys.argv = sys.argv_saved
H = L.N.ROOT / "data" / "interim" / "history"
L.OUT = H / "scores"
L.PROMPTS = H / "score_prompts"
L.OUT.mkdir(parents=True, exist_ok=True)
_cands = None


def cands():
    global _cands
    if _cands is None:
        _cands = {}
        for f in glob.glob(str(H / "candidates" / "*.json")):
            _cands.update(json.load(open(f)))
    return _cands


def queue():
    ev = json.loads((H / "events.json").read_text())
    return sorted(ev, key=lambda e: (e["year"], e["week"], e["percentage"]), reverse=True)


def slices(e):
    ids = list(range(len(cands()[e["id"]]["candidates"])))   # id = rank in the event's candidate list
    random.Random(L.SEED).shuffle(ids)
    return [ids[k:k + L.SLICE] for k in range(0, len(ids), L.SLICE)]


L.queue, L.slices, L.fmt = queue, slices, (lambda e: (L.CHARS, L.SLICE, L.PROMPTS))


def prepare():
    cache = {}
    def text(m, l):
        if m not in cache:
            if len(cache) > 6:
                cache.pop(next(iter(cache)))
            with (H / "texts" / f"{m}.jsonl").open(encoding="utf-8") as f:
                cache[m] = [json.loads(x)["text"] for x in f]
        return cache[m][int(l)]
    for n, e in enumerate(queue()):
        d = L.PROMPTS / e["id"]
        if (d / "done").exists():
            continue
        d.mkdir(parents=True, exist_ok=True)
        cand = cands()[e["id"]]["candidates"]
        for k, ids in enumerate(slices(e)):
            block = "\n\n".join(f"[id {i}] {text(cand[i][0], cand[i][1])[:L.CHARS]}" for i in ids)
            (d / f"slice_{k:03d}.txt").write_text(L.R.PROMPT.format(
                week=f"{e['year']}-W{e['week']:02d}", name=e["name"], quotes="; ".join(e["quotes"]),
                lo=e["window"][0], hi=e["window"][1], posts=block) + L.TAIL)
        (d / "done").touch()
        if n % 200 == 0:
            print(n, flush=True)
    print("prompts written")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "prepare":
        prepare()
    elif a[0] == "status":
        L.status()
    else:
        until = int(a[a.index("--until") + 1]) if "--until" in a else 0
        if until:
            orig = L.limits_used
            L.limits_used = lambda: (100.0, 100.0) if time.time() >= until else orig()
        L.run(int(a[a.index("--workers") + 1]) if "--workers" in a else 12)
