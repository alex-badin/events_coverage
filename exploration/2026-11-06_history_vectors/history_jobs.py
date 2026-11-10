#!/usr/bin/env python
"""Candidate search for the 2,780 events before 2025-W12: event list and probes as in new_weeks, grouped by search
window so that Neo reads each window once. Output data/interim/history: events.json, probes.npy (float16, one row per
probe), jobs.json (per window: the line range in each month file; per event: its probe rows)."""
import ast, bisect, json, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-11-03_new_weeks"))
import new_weeks as N  # noqa: E402
import duckdb
M = N.M
OUT = N.ROOT / "data" / "interim" / "history"
con = duckdb.connect(str(N.ROOT / "data" / "warehouse" / "events.duckdb"), read_only=True)
rows = con.sql("""select event_id, fom_year, fom_week, event_name, quote_examples, attention_percentage, match_start, match_end_exclusive
                  from int_events_with_themes where event_kind = 'specific event' and fom_year * 100 + fom_week < 202512
                  order by fom_year, fom_week, attention_percentage desc""").fetchall()
ev = [{"id": r[0], "year": r[1], "week": r[2], "name": r[3], "quotes": ast.literal_eval(r[4]) if r[4] else [], "percentage": r[5],
       "window": [r[6].isoformat(), r[7].isoformat()]} for r in rows]
(OUT / "events.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1))
dates = {}
for p in sorted((OUT / "texts").glob("*.jsonl")):
    with p.open(encoding="utf-8") as f:
        dates[p.stem] = [json.loads(l)["date"][:10] for l in f]
start = 0
texts, spans = [], []
for e in ev:
    probes = M.build_probes({"name": e["name"], "quotes": e["quotes"]})
    spans.append((start, start + len(probes)))
    texts += probes
    start += len(probes)
print(f"{len(ev)} events, {len(texts)} probes", flush=True)
done = OUT / "probes.npy"
if not done.exists():
    Q = []
    for k in range(0, len(texts), 64):
        Q.append(M.embed_texts_qwen3(texts[k:k + 64]).astype(np.float16))
        if k % 6400 == 0:
            print(k, flush=True)
    np.save(done, np.vstack(Q))
groups = defaultdict(list)
for e, s in zip(ev, spans):
    groups[tuple(e["window"])].append({"id": e["id"], "probes": list(s)})
jobs = []
for (lo, hi), items in sorted(groups.items()):
    ranges = {}
    for m, d in dates.items():
        a, b = bisect.bisect_left(d, lo), bisect.bisect_left(d, hi)
        if b > a:
            ranges[m] = [a, b]
    jobs.append({"lo": lo, "hi": hi, "ranges": ranges, "events": items})
(OUT / "jobs.json").write_text(json.dumps(jobs))
print(f"{len(jobs)} windows; largest {max(len(j['events']) for j in jobs)} events")
