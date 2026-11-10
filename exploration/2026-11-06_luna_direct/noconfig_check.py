#!/usr/bin/env python
"""Does dropping the account config (--ignore-user-config, no MCP servers per call) change the score method's F1?"""
import json, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-10-26_ten_events_readers"))
import report as RP, ten as T, decisions_cost as D  # noqa: E402
import re
S = HERE.parents[1] / "data" / "interim" / "luna_direct"
TAIL = re.search(r'TAIL = """\n(.*?)"""', (HERE / "luna_scores.py").read_text(), re.S).group(0)[len('TAIL = """'):-3]
PROMPTS = S.parent / "ten_events_readers" / "reader_labelling" / "prompts"
OUT = S / "variants" / "score_noconfig"; OUT.mkdir(exist_ok=True)
EVENTS = ["trump_statements_2025w10", "putin_lukashenko_2025w11", "drones_moscow_2025w11"]
def one(p):
    o = OUT / f"{p.stem}.json"
    if o.exists() and o.stat().st_size: return
    with tempfile.TemporaryDirectory() as w:
        subprocess.run(["codex-secondary", "exec", "--ignore-user-config", "--skip-git-repo-check", "-C", w, "-s", "read-only", "--ephemeral", "-m", "gpt-6-luna",
                        "-c", 'model_reasoning_effort="low"', "--output-schema", str(S / "score_schema.json"), "-o", str(o), "-"],
                       input=p.read_text() + TAIL, capture_output=True, text=True, timeout=600)
with ThreadPoolExecutor(6) as pool:
    list(pool.map(one, [p for e in EVENTS for p in PROMPTS.glob(f"{e}_*.txt")]))
for slug in EVENTS:
    r = []
    for v in ("score", "score_noconfig"):
        s = {}
        for p in (S / "variants" / v).glob(f"{slug}_*.json"):
            if p.stat().st_size:
                s.update({int(x["id"]): x["score"] / 100 for x in json.loads(p.read_text())["scores"] if str(x["id"]).isdigit()})
        e = D.evaluate(s, slug); r.append((v, len(s), round(e["f1"], 3), round(e["best"], 3)))
    print(slug, r)
