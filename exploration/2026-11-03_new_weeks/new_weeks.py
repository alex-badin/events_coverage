#!/usr/bin/env python
"""Match the FOM events of 2025-W12..2026-W43 (870 specific events) to posts, with the method chosen in
exploration/2026-10-26_ten_events_readers/: cleaned full text, Qwen3 fragment vectors, best fragment
against the event probes, 3,000 candidates; an event brief written by Codex; every candidate scored by
the OpenAI Decisions API in the cheap layout (question once in the shared input, `choice` yes/no,
first 400 characters, 400 questions per request); the cut-off set by gpt-6-luna reading 100 candidates
drawn from ten probability bands. Budget: $55 for the whole task (Alex, 2026-11-03), ledger spend.jsonl.

    python new_weeks.py events             # event list from the warehouse -> events.json
    python new_weeks.py prepare            # posts of the period, cleaned -> texts.jsonl (free)
    python new_weeks.py embed              # paid: Qwen3 fragment vectors via OpenRouter
    python new_weeks.py cosine [N]         # free: candidates per event
    python new_weeks.py brief_prompts      # free; then zsh ../2026-10-17_jev_selection/codex_answer.sh <OUT>/briefs
    python new_weeks.py decide [N]         # paid: Decisions API on the 3,000 candidates
    python new_weeks.py luna [N]           # paid (cents): the 100-post sample and its cut-off
    python new_weeks.py cutoff_prompts     # free: the same sample for scored events without a cut-off;
                                           # zsh ../2026-10-17_jev_selection/codex_answer.sh <OUT>/cutoffs
    python new_weeks.py cutoff_collect     # Codex answers -> cut-offs, reader recorded per event
    python new_weeks.py export             # data/processed/event_<id>_fulltext_dataset.csv + manifest
N limits a step to the pilot (the first N events of PILOT order).
"""
from __future__ import annotations

import base64
import collections
import concurrent.futures
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
from bisect import bisect_left
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "exploration" / "2026-10-17_fulltext_vs_summary"))
sys.path.insert(0, str(ROOT / "exploration" / "2026-10-17_jev_selection"))
import run as R  # noqa: E402  (cleaning, fragments, the labelling prompt)
import briefs as B  # noqa: E402
import evaluate as V  # noqa: E402
from events_coverage import matching as M  # noqa: E402

OUT = ROOT / "data" / "interim" / "new_weeks"
OUT.mkdir(parents=True, exist_ok=True)
ARCHIVE = ROOT / "news_data" / "ask_media_unified_messages_20260604.db"
PREVIEWS = ROOT / "news_data" / "telegram_previews_2026-11-03.sqlite"
ARCHIVE_END = "2025-04-02T19:16:15"
LEDGER = OUT / "spend.jsonl"
CAP_USD = 55.0
TOP_K, SHOW_CHARS, PER_REQUEST = 3000, 400, 400
DEC_PRICE_PER_M = 0.10
LUNA_PRICE = (0.10, 0.50)           # per 1M input / output tokens
SAMPLE_N, SEED = 100, 17
LAST_COMPLETE_WEEK = 202620         # the run stopped here; the 13 pilot events after it stay out of the warehouse
LUNA_READER = "gpt-6-luna, OpenAI API, effort low"
CODEX_READER = "gpt-6.1-sol, Codex subscription, effort medium"
DECIDE_PER_EVENT, LUNA_PER_EVENT = 0.07, 0.0035   # measured on the pilot ($0.060, $0.003), rounded up


# ------------------------------------------------------------------------------ ledger
def spent():
    return sum(json.loads(l)["usd"] for l in LEDGER.read_text().splitlines()) if LEDGER.exists() else 0.0


def book(step, usd, **extra):
    with LEDGER.open("a") as f:
        f.write(json.dumps({"step": step, "usd": round(usd, 5), "date": time.strftime("%Y-%m-%d %H:%M"), **extra}) + "\n")


def guard():
    if spent() > CAP_USD:
        raise SystemExit(f"stopping: ${spent():.2f} spent of the ${CAP_USD} budget")


# ------------------------------------------------------------------------------ events
def events_step():
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "warehouse" / "events.duckdb"), read_only=True)
    rows = con.sql("""select event_id, fom_year, fom_week, event_name, quote_examples, attention_percentage,
                             match_start, match_end_exclusive
                      from int_events_with_themes
                      where event_kind = 'specific event' and fom_year * 100 + fom_week >= 202512
                      order by fom_year, fom_week, attention_percentage desc""").fetchall()
    import ast
    ev = [{"id": r[0], "year": r[1], "week": r[2], "name": r[3], "quotes": ast.literal_eval(r[4]) if r[4] else [],
           "percentage": r[5], "window": [r[6].isoformat(), r[7].isoformat()]} for r in rows]
    (OUT / "events.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1))
    print(f"{len(ev)} events, {ev[0]['year']}-W{ev[0]['week']} .. {ev[-1]['year']}-W{ev[-1]['week']}")


def events():
    return json.loads((OUT / "events.json").read_text())


def pilot_order():
    """Every event, the pilot first: 50 events spread evenly over the period (every k-th in date order)."""
    ev = events()
    k = len(ev) / 50
    first = [ev[int(j * k)] for j in range(50)]
    ids = {e["id"] for e in first}
    return first + [e for e in ev if e["id"] not in ids]


def todo(n):
    ev = pilot_order()
    return ev[:int(n)] if n else ev


# ----------------------------------------------------------------------------- prepare
def prepare():
    """Posts of every in-scope channel from the earliest window start: the archive up to its end, the
    previews after it; cleaned as in the ten-event test, repeated per-channel endings found per channel
    and calendar month. Sorted by date so a window is one contiguous range."""
    target = OUT / "texts.jsonl"
    if target.exists():
        print("texts.jsonl exists"); return
    lo = min(e["window"][0] for e in events())
    archived = M.load_archived_sources()
    posts = []
    a = sqlite3.connect(f"file:{ARCHIVE}?mode=ro", uri=True)
    for source, mid, d, text, views in a.execute(
            "SELECT source, message_id, date, original_message, views FROM unified_messages WHERE date >= ?", (lo,)):
        if source not in archived and text:
            posts.append({"source": source, "message_id": str(mid), "date": d.replace(" ", "T"),
                          "raw": " ".join(R.normalize_text(text, None, max_chars=10**9).split()), "views": views})
    have = {(p["source"], p["message_id"]) for p in posts}
    b = sqlite3.connect(f"file:{PREVIEWS}?mode=ro", uri=True)
    for source, mid, d, text, views in b.execute(
            "SELECT source_id, message_id, published_utc, text, views_text FROM posts WHERE record_type = 'text'"):
        if source not in archived and (source, str(mid)) not in have:
            posts.append({"source": source, "message_id": str(mid), "date": d, "raw": " ".join(text.split()),
                          "views": parse_views(views)})
    posts.sort(key=lambda p: p["date"])
    groups = collections.defaultdict(list)
    for p in posts:
        groups[(p["source"], p["date"][:7])].append(p["raw"])
    index = collections.defaultdict(list)
    for texts in groups.values():
        for ending, *_ in R.find_footers(texts):
            index[" ".join(ending.split()[-2:])].append(ending)
    for k in index:
        index[k] = sorted(set(index[k]), key=len, reverse=True)
    with target.open("w", encoding="utf-8") as f:
        for p in posts:
            p["text"] = R.clean(R.strip_footers(p.pop("raw"), index))
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"{len(posts):,} posts, {sum(1 for p in posts if p['text']):,} with text, "
          f"{sum(len(list(R.chunks(p['text']))) for p in posts if p['text']):,} fragments")


def parse_views(s):
    if not s:
        return None
    m = re.fullmatch(r"([\d.]+)\s*([KM]?)", s.strip())
    if not m:
        return None
    return int(float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6}[m.group(2)])


_posts = None


def posts():
    global _posts
    if _posts is None:
        with (OUT / "texts.jsonl").open(encoding="utf-8") as f:
            _posts = [json.loads(l) for l in f]
    return _posts


# ------------------------------------------------------------------------------- embed
def embed():
    """Same call as the ten-event test (run.embed): 650/120-character fragments, 64 per request,
    qwen3-embedding-8b on DeepInfra via OpenRouter, float16, L2-normalised."""
    folder = OUT / "fragments"
    folder.mkdir(exist_ok=True)
    ps = posts()
    if not (folder / "owners.npy").exists():
        owners = [i for i, p in enumerate(ps) if p["text"] for _ in R.chunks(p["text"])]
        np.save(folder / "owners.npy", np.array(owners, np.int32))
    rows = [c for p in ps if p["text"] for c in R.chunks(p["text"])]
    size = 64
    tasks = [(i, rows[i:i + size]) for i in range(0, len(rows), size) if not (folder / f"part_{i // size:06d}.npy").exists()]
    key, lock, paid = M.get_openrouter_key(), threading.Lock(), {"usd": 0.0, "tokens": 0, "n": 0}
    print(f"{len(rows):,} fragments, {len(tasks):,} requests to go", flush=True)

    def one(task):
        i, texts = task
        if spent() + paid["usd"] > CAP_USD:
            return "budget"
        body = {"model": M.QWEN_MODEL, "input": texts, "encoding_format": "base64",
                "provider": {"order": [M.QWEN_PROVIDER], "allow_fallbacks": False}}
        for attempt in range(6):
            try:
                req = urllib.request.Request(M.QWEN_API_URL, data=json.dumps(body).encode(), method="POST")
                req.add_header("Authorization", f"Bearer {key}")
                req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=120) as r:
                    result = json.loads(r.read())
                break
            except Exception as error:  # noqa: BLE001 — retried, then reported
                if attempt == 5:
                    return str(error)[:80]
                time.sleep(2 ** attempt)
        data = sorted(result["data"], key=lambda r: r["index"])
        X = np.array([np.frombuffer(base64.b64decode(r["embedding"]), dtype="<f4") for r in data], np.float32)
        if len(X) != len(texts):
            return "missing rows"
        X /= np.linalg.norm(X, axis=1, keepdims=True)
        np.save(folder / f"part_{i // size:06d}.npy", X.astype(np.float16))
        u = result.get("usage", {})
        with lock:
            paid["usd"] += u.get("cost") or u.get("prompt_tokens", 0) / 1e6 * R.PRICE_PER_M
            paid["tokens"] += u.get("prompt_tokens", 0)
            paid["n"] += 1
            if paid["n"] % 500 == 0:   # the ledger gets the spend in slices, so a crash loses little
                book("embed", paid["usd"], requests=paid["n"], input_tokens=paid["tokens"])
                print(f"{paid['n']:,} requests, {paid['tokens']:,} tokens, ${paid['usd']:.3f}; total ${spent():.2f}", flush=True)
                paid.update(usd=0.0, tokens=0)
        return None

    errors = collections.Counter()
    try:
        with concurrent.futures.ThreadPoolExecutor(16) as pool:
            for e in pool.map(one, tasks):
                if e:
                    errors[e] += 1
    finally:
        book("embed", paid["usd"], requests=paid["n"] % 500, input_tokens=paid["tokens"])
    print(f"done; errors {dict(errors)}; total ${spent():.2f}")


_owners = None
SIZE = 64                           # fragments per part file (the last part may hold fewer)


def owners():
    global _owners
    if _owners is None:
        _owners = np.load(OUT / "fragments" / "owners.npy")
        n = len(list((OUT / "fragments").glob("part_*.npy")))
        assert n == -(-len(_owners) // SIZE), "fragment vectors incomplete; rerun embed"
    return _owners


def fragment_rows(lo, hi):
    """Vectors of fragments lo..hi-1, read from the part files that hold them."""
    parts = [np.load(OUT / "fragments" / f"part_{k:06d}.npy") for k in range(lo // SIZE, (hi - 1) // SIZE + 1)]
    X = np.vstack(parts)
    return X[lo - (lo // SIZE) * SIZE: hi - (lo // SIZE) * SIZE]


# ------------------------------------------------------------------------------ cosine
def cosine(n=None):
    """Best fragment of each window post against the event probes (name, each quote, both together)."""
    ps = posts()
    dates = [p["date"][:10] for p in ps]
    own = owners()
    folder = OUT / "scores"
    folder.mkdir(exist_ok=True)
    for e in todo(n):
        target = folder / f"{e['id']}.json"
        if target.exists():
            continue
        a, b = bisect_left(dates, e["window"][0]), bisect_left(dates, e["window"][1])
        fa, fb = int(np.searchsorted(own, a)), int(np.searchsorted(own, b))
        probes = M.build_probes({"name": e["name"], "quotes": e["quotes"]})
        Q = M.embed_texts_qwen3(probes).astype(np.float32)
        best = np.full(b - a, -1.0, np.float32)
        X = fragment_rows(fa, fb)
        for k in range(0, len(X), 50000):
            s = (X[k:k + 50000].astype(np.float32) @ Q.T).max(axis=1)
            np.maximum.at(best, own[fa + k:fa + k + len(s)] - a, s)
        order = np.argsort(-best)[:TOP_K]
        cand = [{"i": int(a + j), "cos": round(float(best[j]), 4)} for j in order if best[j] > -1]
        target.write_text(json.dumps({"id": e["id"], "probes": probes, "window_posts": b - a,
                                      "window_posts_with_text": int((best > -1).sum()), "candidates": cand}))
        book("cosine", len(probes) * 20 / 1e6 * R.PRICE_PER_M, event=e["id"])
    print("cosine done")


def candidates(e):
    return json.loads((OUT / "scores" / f"{e['id']}.json").read_text())["candidates"]


# ------------------------------------------------------------------------------ briefs
def brief_prompts():
    """The ten-event test's brief prompt (briefs.PROMPT): FOM name, every respondent wording, window,
    the 40 closest posts (first 500 characters)."""
    ps = posts()
    folder = OUT / "briefs" / "prompts"
    folder.mkdir(parents=True, exist_ok=True)
    (OUT / "briefs" / "schema.json").write_text(json.dumps({
        "type": "object", "additionalProperties": False, "required": ["what_happened", "counts", "does_not_count"],
        "properties": {k: {"type": "string"} for k in ["what_happened", "counts", "does_not_count"]}}, indent=2))
    n = 0
    for e in pilot_order():
        if not (OUT / "scores" / f"{e['id']}.json").exists() or (folder / f"{e['id']}.txt").exists():
            continue
        block = "\n\n".join(f"[{ps[c['i']]['date'][:10]}] {ps[c['i']]['text'][:500]}" for c in candidates(e)[:40])
        (folder / f"{e['id']}.txt").write_text(B.PROMPT.format(
            name=e["name"], week=f"{e['year']}-W{e['week']:02d}", quotes="; ".join(e["quotes"]),
            lo=e["window"][0], hi=e["window"][1], posts=block), encoding="utf-8")
        n += 1
    print(f"{n} prompts")


def brief(e):
    p = OUT / "briefs" / "out" / f"{e['id']}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ----------------------------------------------------------------------------- decide
def question(e):
    """Jev v3's question and criteria, all in the shared input (the cheap layout)."""
    b = brief(e)
    block = {"event": e["name"], "how_respondents_described_it": e["quotes"],
             "survey_week": f"{e['year']}-W{e['week']:02d}", "search_window": f"{e['window'][0]} — {e['window'][1]}",
             "what_happened": b["what_happened"], "counts_as_coverage": b["counts"], "does_not_count": b["does_not_count"],
             "question": ("Does the news post in the state report on or discuss `event` (the event itself, its course, "
                          "reactions to it, its direct consequences)? Judge by the text of the post.")}
    ask = ("Answer true if: The post reports on or discusses this event. Answer false if: The post is about something "
           "else, including a similar event of the same kind (another disaster, other negotiations, other prices), "
           "or mentions the topic only in passing.")
    return json.dumps({**block, "answer": ask}, ensure_ascii=False)


def _openai():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(ROOT / ".env")
    # max_retries=0: on 2026-11-03 OpenAI billed 1,584 requests (134M tokens, $13.43) that no file
    # recorded, most likely the SDK's silent retries. Every attempt now goes through patiently() and
    # into attempts.jsonl.
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)


def patiently(call):
    """Our own retry, one line in attempts.jsonl per attempt (a failed attempt may still be billed). Waits out
    the per-minute token limit and server errors; a spent budget (insufficient_quota) stops at once."""
    import openai
    for attempt in range(8):
        started = time.time()
        try:
            result = call()
            log_attempt(attempt, "ok", time.time() - started)
            return result
        except (openai.RateLimitError, openai.APIStatusError, openai.APIConnectionError) as error:
            status = getattr(error, "status_code", None) or type(error).__name__
            log_attempt(attempt, status, time.time() - started, str(error)[:200])
            if "insufficient_quota" in str(error) or attempt == 7 or status in (400, 401, 403, 404):
                raise
            time.sleep(min(10 + 5 * attempt, 60))


_attempts_lock = threading.Lock()


def log_attempt(attempt, status, seconds, note=""):
    with _attempts_lock, (OUT / "attempts.jsonl").open("a") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "attempt": attempt, "status": status,
                            "seconds": round(seconds, 1), "note": note}) + "\n")


def decide(n=None):
    ps, client = posts(), _openai()
    folder = OUT / "decisions"
    folder.mkdir(exist_ok=True)

    def one(e):
        target = folder / f"{e['id']}.json"
        have = json.loads(target.read_text()) if target.exists() else {"p": {}, "usage": []}
        ids = [c["i"] for c in candidates(e) if str(c["i"]) not in have["p"]]
        shared, usd = question(e), 0.0
        for k in range(0, len(ids), PER_REQUEST):
            chunk = ids[k:k + PER_REQUEST]
            body = {"model": "gpt-6-luna", "input": shared, "questions": [
                {"type": "choice", "name": f"p{i}", "instructions": "News post:\n" + ps[i]["text"][:SHOW_CHARS],
                 "choices": [{"value": "yes"}, {"value": "no"}]} for i in chunk]}
            d = patiently(lambda: client.post("/decisions", body=body, cast_to=object))
            for a in d["answers"]:
                pr = {x["value"]: x["probability"] for x in a.get("probabilities") or []}
                if "yes" in pr:
                    have["p"][a["name"][1:]] = round(float(pr["yes"]), 4)
            u = d.get("usage") or {}
            have["usage"].append(u)
            paid = u.get("input_tokens", 0) * DEC_PRICE_PER_M / 1e6
            usd += paid
            target.write_text(json.dumps(have))            # saved after every billed request
            book("decide", paid, event=e["id"], input_tokens=u.get("input_tokens", 0))   # and booked with it
        return usd

    evs = [e for e in todo(n) if brief(e) and not (folder / f"{e['id']}.json").exists()
           or (folder / f"{e['id']}.json").exists() and len(json.loads((folder / f"{e['id']}.json").read_text())["p"]) < len(candidates(e)) - 5]
    lock = threading.Lock()
    # Stop early enough that every scored event can still get its cut-off inside the budget: a
    # score without a cut-off is money spent for nothing. Room for the four events in flight too.
    waiting = [len([e for e in events() if (folder / f"{e['id']}.json").exists()
                    and not (OUT / "luna" / f"{e['id']}.json").exists()])]

    def run(e):
        if spent() + 4 * DECIDE_PER_EVENT + waiting[0] * LUNA_PER_EVENT > CAP_USD:
            return 0.0
        usd = one(e)
        with lock:
            waiting[0] += 1
        return usd

    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        total = sum(pool.map(run, evs))
    print(f"{len(evs)} events, ${total:.3f}; total ${spent():.2f}")


def scores(e):
    p = OUT / "decisions" / f"{e['id']}.json"
    return {int(k): v for k, v in json.loads(p.read_text())["p"].items()} if p.exists() else None


# ------------------------------------------------------------------------------- luna
def sample(e):
    """100 candidates drawn evenly from ten equal-width probability bands (evaluate.sample_cut), seed 17;
    each pick weighted by its band's size."""
    s = scores(e)
    ids = [c["i"] for c in candidates(e) if c["i"] in s]
    lo, hi = min(s[i] for i in ids), max(s[i] for i in ids)
    edges = np.linspace(lo, hi, V.BANDS + 1)
    band = {i: min(int(np.searchsorted(edges, s[i], side="right")) - 1, V.BANDS - 1) for i in ids}
    rng = np.random.default_rng(SEED)
    picked, w = [], {}
    for b in range(V.BANDS):
        m = [i for i in ids if band[i] == b]
        if not m:
            continue
        take = rng.choice(len(m), size=min(SAMPLE_N // V.BANDS, len(m)), replace=False)
        for t in take:
            picked.append(m[t]); w[m[t]] = len(m) / len(take)
    return picked, w


def luna(n=None):
    ps, client = posts(), _openai()
    schema = json.loads((R.OUT / "labels" / "schema.json").read_text())
    folder = OUT / "luna"
    folder.mkdir(exist_ok=True)

    def one(e):
        target = folder / f"{e['id']}.json"
        if target.exists() or scores(e) is None:
            return 0.0
        guard()
        picked, w = sample(e)
        labels, usd = {}, 0.0
        for k in range(0, len(picked), 50):
            block = "\n\n".join(f"[id {i}] {ps[i]['text'][:2500]}" for i in picked[k:k + 50])
            text = R.PROMPT.format(week=f"{e['year']}-W{e['week']:02d}", name=e["name"], quotes="; ".join(e["quotes"]),
                                   lo=e["window"][0], hi=e["window"][1], posts=block)
            d = patiently(lambda: client.chat.completions.create(
                model="gpt-6-luna", messages=[{"role": "user", "content": text}], reasoning_effort="low",
                response_format={"type": "json_schema", "json_schema": {"name": "labels", "strict": True,
                                                                        "schema": schema}})).model_dump()
            u = d.get("usage") or {}
            usd += (u.get("prompt_tokens", 0) * LUNA_PRICE[0] + u.get("completion_tokens", 0) * LUNA_PRICE[1]) / 1e6
            for x in json.loads(d["choices"][0]["message"]["content"])["labels"]:
                if str(x["id"]).strip().isdigit():
                    labels[int(str(x["id"]).strip())] = x["label"] == "yes"
        s = scores(e)
        got = [i for i in picked if i in labels]
        cut = V.best_cut(got, labels, w, s) if any(labels[i] for i in got) else 1.01
        target.write_text(json.dumps({"labels": {str(i): labels[i] for i in got}, "weights": {str(i): w[i] for i in got},
                                      "missing": [i for i in picked if i not in labels], "cut": cut, "usd": usd}))
        book("luna", usd, event=e["id"])
        return usd

    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        total = sum(pool.map(one, todo(n)))
    print(f"${total:.4f}; total ${spent():.2f}")


# ------------------------------------------------------------------------- codex cut-offs
def cutoff_prompts():
    """Scored events with no cut-off yet: the same 100-post sample and prompt as luna(), read by Codex
    (subscription) instead of the API. One prompt per event."""
    ps = posts()
    folder = OUT / "cutoffs" / "prompts"
    folder.mkdir(parents=True, exist_ok=True)
    (OUT / "cutoffs" / "schema.json").write_text((R.OUT / "labels" / "schema.json").read_text())
    n = 0
    for e in events():
        if scores(e) is None or (OUT / "luna" / f"{e['id']}.json").exists():
            continue
        picked, _ = sample(e)
        block = "\n\n".join(f"[id {i}] {ps[i]['text'][:2500]}" for i in picked)
        (folder / f"{e['id']}.txt").write_text(R.PROMPT.format(
            week=f"{e['year']}-W{e['week']:02d}", name=e["name"], quotes="; ".join(e["quotes"]),
            lo=e["window"][0], hi=e["window"][1], posts=block), encoding="utf-8")
        n += 1
    print(f"{n} prompts")


def cutoff_collect():
    """Codex answers -> luna/<id>.json with the reader named; existing Luna files are not touched."""
    n = skipped = 0
    for e in events():
        target, answer = OUT / "luna" / f"{e['id']}.json", OUT / "cutoffs" / "out" / f"{e['id']}.json"
        if target.exists() or not answer.exists():
            continue
        picked, w = sample(e)
        labels = {int(str(x["id"]).strip()): x["label"] == "yes" for x in json.loads(answer.read_text())["labels"]
                  if str(x["id"]).strip().isdigit()}
        got = [i for i in picked if i in labels]
        if len(got) < 0.95 * len(picked):
            print(f"{e['id']}: answer covers {len(got)} of {len(picked)}; rerun"); answer.unlink(); skipped += 1
            continue
        s = scores(e)
        cut = V.best_cut(got, labels, w, s) if any(labels[i] for i in got) else 1.01
        target.write_text(json.dumps({"labels": {str(i): labels[i] for i in got}, "weights": {str(i): w[i] for i in got},
                                      "missing": [i for i in picked if i not in labels], "cut": cut, "usd": 0.0,
                                      "reader": CODEX_READER}))
        n += 1
    print(f"{n} cut-offs written, {skipped} to rerun")


# ------------------------------------------------------------------------------ export
def export():
    """One dataset CSV and manifest per event in data/processed, in the shape load_warehouse.py reads."""
    import csv
    ps = posts()
    out_dir = ROOT / "data" / "processed"
    done, empty = [], []    # events with matched posts / searched with nothing kept (no dataset file)
    table = []
    for e in events():
        lp = OUT / "luna" / f"{e['id']}.json"
        if not lp.exists():
            continue
        if e["year"] * 100 + e["week"] > LAST_COMPLETE_WEEK:   # one event in a week is not that week's picture
            continue
        lj, s = json.loads(lp.read_text()), scores(e)
        cut, reader = lj["cut"], lj.get("reader", LUNA_READER)
        cos = {c["i"]: c["cos"] for c in candidates(e)}
        kept = [i for i in cos if s.get(i, 0) >= cut]
        slug = f"event_{e['id']}_fulltext"
        (empty if not kept else done).append(slug)
        with (out_dir / f"{slug}_dataset.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["source", "message_id", "date", "is_digest", "summary", "original_message", "views",
                        "forwards", "cosine_max", "rerank_score", "keyword_match"])
            for i in sorted(kept, key=lambda i: -s[i]):
                p = ps[i]
                w.writerow([p["source"], p["message_id"], p["date"], "", "", p["text"], p["views"] or "", "",
                            cos[i], s[i], ""])
        sc = json.loads((OUT / "scores" / f"{e['id']}.json").read_text())
        (out_dir / f"{slug}_manifest.json").write_text(json.dumps({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": {"name": e["name"], "year": e["year"], "week": e["week"], "fom_percentage": e["percentage"],
                      "quotes": e["quotes"], "event_id": e["id"]},
            "window": {"match_start": e["window"][0], "match_end_exclusive": e["window"][1]},
            "models": {"retriever": "qwen3_fulltext", "embed_model": M.QWEN_MODEL,
                       "rerank_model": "gpt-6-luna /v1/decisions (choice yes/no, 400 chars)",
                       "cut_reader": reader, "brief": "gpt-6.1-sol via Codex"},
            "params": {"top_k": TOP_K, "rerank_threshold": cut, "show_chars": SHOW_CHARS},
            "counts": {"candidates": len(cos), "kept": len(kept), "embedded_pool": sc["window_posts_with_text"],
                       "window_posts": sc["window_posts"]}}, ensure_ascii=False, indent=1))
        if not kept:
            (out_dir / f"{slug}_dataset.csv").unlink()
        table.append([e["id"], f"{e['year']}-W{e['week']:02d}", e["name"], e["percentage"], reader, cut, len(kept),
                      len(lj["labels"]), sum(lj["labels"].values()), len(lj["missing"])])
    (OUT / "exported_slugs.json").write_text(json.dumps(done, indent=0))
    (OUT / "exported_empty_slugs.json").write_text(json.dumps(empty, indent=0))
    with (HERE / "cutoffs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "week", "event", "fom_percentage", "cut_reader", "cut", "kept_posts",
                    "sample_labelled", "sample_yes", "sample_missing"])
        w.writerows(table)
    print(f"{len(done)} events with posts, {len(empty)} with none")


if __name__ == "__main__":
    step, arg = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    {"events": events_step, "prepare": prepare, "embed": embed, "cosine": lambda: cosine(arg),
     "brief_prompts": brief_prompts, "decide": lambda: decide(arg), "luna": lambda: luna(arg),
     "cutoff_prompts": cutoff_prompts, "cutoff_collect": cutoff_collect, "export": export}[step]()
