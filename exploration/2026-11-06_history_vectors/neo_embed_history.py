"""Runs on Neo: Qwen3 vectors of cleaned full text, 650/120-character fragments, as new_weeks.embed. One month at a
time: <month>.f16 (float16, 4096 numbers per fragment), <month>.owners.npy (line number of the post in that month's
file), spend.jsonl. Stops before the budget. A month is written under its final name only when complete.
    python neo_embed_history.py <dir with *.txt.gz> <output dir> <cap usd> [first month] [last month]"""
import base64, concurrent.futures, glob, gzip, json, os, sys, threading, time, urllib.request
import numpy as np

SRC, OUT, CAP = sys.argv[1], sys.argv[2], float(sys.argv[3])
FIRST, LAST = (sys.argv[4] if len(sys.argv) > 4 else ""), (sys.argv[5] if len(sys.argv) > 5 else "9999")
URL, MODEL, PROVIDER = "https://openrouter.ai/api/v1/embeddings", "qwen/qwen3-embedding-8b", "DeepInfra"
DIM, SIZE, WIDTH, OVERLAP, WORKERS = 4096, 64, 650, 120, 16
KEY = os.environ.get("OPENROUTER_API_KEY") or next(l.split("=", 1)[1].strip().strip('"') for l in open(r"C:\emb_test\ec\.env") if l.startswith("OPENROUTER"))
os.makedirs(OUT, exist_ok=True)
LEDGER = os.path.join(OUT, "spend.jsonl")
lock = threading.Lock()


def spent():
    return sum(json.loads(l)["usd"] for l in open(LEDGER)) if os.path.exists(LEDGER) else 0.0


def chunks(text):
    start = 0
    while start < len(text):
        end = min(start + WIDTH, len(text))
        yield text[start:end]
        if end == len(text):
            break
        start = end - OVERLAP


def month(path):
    name = os.path.basename(path)[:-7]
    target = os.path.join(OUT, name + ".f16")
    if os.path.exists(target) or not FIRST <= name <= LAST:
        return
    rows, owners = [], []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for n, line in enumerate(f):
            for c in chunks(json.loads(line)):
                rows.append(c); owners.append(n)
    tmp = target + ".tmp"
    X = np.memmap(tmp, dtype="<f2", mode="w+", shape=(len(rows), DIM))
    paid = {"usd": 0.0, "tokens": 0, "requests": 0}
    base = spent()

    def one(k):
        body = json.dumps({"model": MODEL, "input": rows[k:k + SIZE], "encoding_format": "base64",
                           "provider": {"order": [PROVIDER], "allow_fallbacks": False}}).encode()
        for attempt in range(6):
            try:
                req = urllib.request.Request(URL, data=body, method="POST",
                                             headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    res = json.loads(r.read())
                data = sorted(res["data"], key=lambda d: d["index"])
                V = np.array([np.frombuffer(base64.b64decode(d["embedding"]), dtype="<f4") for d in data], np.float32)
                V /= np.linalg.norm(V, axis=1, keepdims=True)
                X[k:k + len(V)] = V.astype(np.float16)
                u = res.get("usage", {})
                with lock:
                    paid["usd"] += u.get("cost") or u.get("prompt_tokens", 0) / 1e6 * 0.01
                    paid["tokens"] += u.get("prompt_tokens", 0)
                    paid["requests"] += 1
                return
            except Exception as e:  # retried, then the month stops
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)

    if base > CAP:
        raise SystemExit("budget")
    t = time.time()
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, range(0, len(rows), SIZE)))
    X.flush()
    del X
    with open(LEDGER, "a") as f:
        f.write(json.dumps({"month": name, "fragments": len(rows), "usd": round(paid["usd"], 5), "tokens": paid["tokens"],
                            "requests": paid["requests"], "seconds": round(time.time() - t)}) + "\n")
    np.save(os.path.join(OUT, name + ".owners.npy"), np.array(owners, np.int32))
    os.replace(tmp, target)
    print(name, len(rows), f"${paid['usd']:.4f} total ${spent():.3f} {time.time() - t:.0f}s", flush=True)


for p in sorted(glob.glob(os.path.join(SRC, "*.txt.gz"))):
    month(p)
print("done", flush=True)
