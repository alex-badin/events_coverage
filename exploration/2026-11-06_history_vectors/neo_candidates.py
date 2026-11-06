"""Runs on Neo. For each search window: best fragment of each post against each event's probes, top 3,000 posts per
event by that similarity (as new_weeks.cosine). Output candidates/<lo>_<hi>.json: {event id: [[month, line, cos], ...]}.
    python neo_candidates.py <folder with jobs.json, probes.npy> <vector folder> <output folder> [first window index] [count]"""
import json, os, sys, time
import numpy as np
BASE, VEC, OUT = sys.argv[1:4]
FIRST, COUNT = int(sys.argv[4]) if len(sys.argv) > 4 else 0, int(sys.argv[5]) if len(sys.argv) > 5 else 10**9
TOP_K, BLOCK, DIM = 3000, 50000, 4096
jobs = json.load(open(os.path.join(BASE, "jobs.json")))
Q_all = np.load(os.path.join(BASE, "probes.npy"), mmap_mode="r")
os.makedirs(OUT, exist_ok=True)
for j in jobs[FIRST:FIRST + COUNT]:
    target = os.path.join(OUT, f"{j['lo']}_{j['hi']}.json")
    if os.path.exists(target) or not all(os.path.exists(os.path.join(VEC, m + ".f16")) for m in j["ranges"]):
        continue
    t = time.time()
    eids = j["events"]
    Q = np.vstack([np.asarray(Q_all[e["probes"][0]:e["probes"][1]], np.float32) for e in eids])
    cuts = np.cumsum([0] + [e["probes"][1] - e["probes"][0] for e in eids])
    months, offsets, n = list(j["ranges"]), {}, 0
    for m in months:
        offsets[m] = n
        n += j["ranges"][m][1] - j["ranges"][m][0]
    best = np.full((n, len(eids)), -1.0, np.float32)
    for m in months:
        a, b = j["ranges"][m]
        own = np.load(os.path.join(VEC, m + ".owners.npy"))
        fa, fb = int(np.searchsorted(own, a)), int(np.searchsorted(own, b))
        X = np.memmap(os.path.join(VEC, m + ".f16"), dtype="<f2", mode="r").reshape(-1, DIM)
        for k in range(fa, fb, BLOCK):
            end = min(k + BLOCK, fb)
            S = np.asarray(X[k:end], np.float32) @ Q.T
            per_event = np.stack([S[:, cuts[i]:cuts[i + 1]].max(axis=1) for i in range(len(eids))], axis=1)
            np.maximum.at(best, own[k:end] - a + offsets[m], per_event)
    out = {}
    for i, e in enumerate(eids):
        order = np.argsort(-best[:, i])[:TOP_K]
        rows = []
        for o in order:
            if best[o, i] <= -1:
                continue
            m = next(x for x in reversed(months) if offsets[x] <= o)
            rows.append([m, int(o - offsets[m] + j["ranges"][m][0]), round(float(best[o, i]), 4)])
        out[e["id"]] = {"window_posts": n, "window_posts_with_text": int((best[:, i] > -1).sum()), "candidates": rows}
    with open(target + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(target + ".tmp", target)
    print(j["lo"], j["hi"], len(eids), "events", n, "posts", f"{time.time() - t:.0f}s", flush=True)
print("done", flush=True)
