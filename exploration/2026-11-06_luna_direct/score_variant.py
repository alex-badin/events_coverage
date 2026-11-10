#!/usr/bin/env python
"""Luna through Codex as a scorer: 0-100 per post instead of yes/no, then the usual per-event cut-off from the
100-post sample (D.evaluate: 200 draws, Luna labels). Also: votes from the three yes/no runs already on disk."""
import json, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-10-26_ten_events_readers"))
import report as RP, ten as T, decisions_cost as D, variants_score as VS  # noqa: E402

S = HERE.parents[1] / "data" / "interim" / "luna_direct"
PROMPTS = S.parent / "ten_events_readers" / "reader_labelling" / "prompts"
EVENTS = T.EVENTS
TAIL = """
Дополнительно: вместо метки дай каждому посту score — целое число от 0 до 100, насколько вероятно, что правильный ответ "yes".
Используй всю шкалу: 0 — точно о другом, 100 — точно об этом событии, средние значения для пограничных и косвенных постов."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["scores"], "properties": {"scores": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["id", "score"],
    "properties": {"id": {"type": "string"}, "score": {"type": "integer"}}}}}}
(S / "variants" / "score").mkdir(parents=True, exist_ok=True)
(S / "score_schema.json").write_text(json.dumps(SCHEMA))


def one(p):
    o = S / "variants" / "score" / f"{p.stem}.json"
    if o.exists() and o.stat().st_size:
        return
    with tempfile.TemporaryDirectory() as w:
        subprocess.run(["codex-secondary", "exec", "--skip-git-repo-check", "-C", w, "-s", "read-only", "--ephemeral", "-m", "gpt-6-luna",
                        "-c", 'model_reasoning_effort="low"', "--output-schema", str(S / "score_schema.json"), "-o", str(o), "-"],
                       input=p.read_text() + TAIL, capture_output=True, text=True, timeout=600)


with ThreadPoolExecutor(16) as pool:
    list(pool.map(one, [p for e in EVENTS for p in PROMPTS.glob(f"{e}_*.txt")]))

rows = []
print("event | score: AUC, best F1, F1 at sample cut | 2-of-3 votes F1 | any-of-3 votes F1 | Decisions F1 | API Luna F1")
for slug in EVENTS:
    maj, (_, w) = RP.majority(slug), T.labels(slug)
    s = {}
    for p in (S / "variants" / "score").glob(f"{slug}_*.json"):
        s.update({int(x["id"]): x["score"] / 100 for x in json.loads(p.read_text())["scores"] if str(x["id"]).isdigit()})
    ev = D.evaluate(s, slug)
    runs = [VS.load(S / "control" / "out", slug), VS.load(S / "variants" / "rerun", slug), VS.load(S / "variants" / "bare", slug)]
    ids = [i for i in maj if all(i in r for r in runs)]
    two = {i: sum(r[i] for r in runs) >= 2 for i in ids}
    any_ = {i: any(r[i] for r in runs) for i in ids}
    api = {int(k): v for k, v in json.loads((T.OUT / "reader_labels" / "gpt-6-luna" / f"{slug}.json").read_text())["labels"].items()}
    dec = D.evaluate(D.load('choice_400_x400', slug)[0], slug)['f1']
    rows.append((ev['f1'], ev['best'], dec))
    print(f"{slug} | {len(s)} scored: {ev['auc']:.3f}, {ev['best']:.3f}, {ev['f1']:.3f} | {VS.f1(two, maj, w)} | {VS.f1(any_, maj, w)} | {D.evaluate(D.load('choice_400_x400', slug)[0], slug)['f1']:.3f} | {VS.f1(api, maj, w)}")
import numpy as np
print("mean sample cut, best, Decisions", np.mean(rows, axis=0).round(3))
