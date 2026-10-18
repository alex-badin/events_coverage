#!/usr/bin/env python
"""Does the first-stage search need the LLM summary, or is the cleaned full text as good?

Compares two Qwen3 document spaces on the same posts and the same query probes:
  summary   — the existing sidecar on Neo (one vector per post, from `summary`)
  fulltext  — the post's own text, cleaned the way misinfo_tracking_moldova does it
              (per-channel repeated endings such as «Подписаться» stripped, then links,
              @handles, '#' and emoji removed), cut into 650-character fragments with
              120 characters of overlap; a post scores by its best fragment.

Ground truth does not come from the pipeline's rerank (it reads `summary`, so it would favour
the summary space): a Codex model reads the full text of every post in the union of both
methods' top 500 per event and says whether it reports on the event.

Steps (each resumable):
  prepare   posts of the test window -> texts.jsonl, footers.csv
  embed     fragments -> Qwen3 vectors (paid, OpenRouter; stops at COST_CAP_USD)
  score     per event: both spaces' cosine for every post in the event window
  prompts   per event: the posts to label, in slices of 50
  report    precision and recall per method -> results.json, printed tables
Labelling runs between `prompts` and `report`: zsh label.sh
"""
from __future__ import annotations

import argparse
import base64
import collections
import concurrent.futures
import csv
import json
import re
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from events_coverage import matching as M  # noqa: E402
from events_coverage.framing import normalize_text  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = ROOT / "data" / "interim" / "fulltext_vs_summary"
COST_CAP_USD = 1.50          # approved budget is $2 for the whole run
PRICE_PER_M = 0.01           # qwen3-embedding-8b on DeepInfra via OpenRouter
FRAG_CHARS, FRAG_OVERLAP = 650, 120
TOP = 500                    # labelled depth per method and event
SLICE = 50

# The pilot events whose window has full text; W05 (DC air crash) is left out because
# January 2025 rows have almost no raw text.
EVENTS = [
    "putin_trump_call_2025w08", "us_russia_contacts_2025w09", "trump_zelensky_2025w10",
    "kursk_2025w11", "prices_2025w11",
]

# Footer detection, same values as misinfo_tracking_moldova config/topic_map.json
FOOTER = {
    "footer_min_posts": 20, "footer_min_share": 0.05, "footer_share_without_marker": 0.30,
    "footer_max_words": 25,
    "footer_markers": ["@", "t.me", "http", "подпис", "подпиш", "subscribe", "|", "¦",
                       "прислать", "наш канал", "канал в", "по ссылке"],
}
URL_RE = re.compile(r"(https?://\S+|t\.me/\S+|www\.\S+)", re.I)
HANDLE_RE = re.compile(r"(?<!\w)@\w+")
DROP_CATEGORIES = {"So", "Sk", "Cs", "Co", "Cf", "Cn"}


# ----------------------------------------------------------------------------- cleaning
def find_footers(texts):
    n = len(texts)
    threshold = max(FOOTER["footer_min_posts"], FOOTER["footer_min_share"] * n)
    counts = collections.Counter()
    for text in texts:
        words = text.split()
        for k in range(2, FOOTER["footer_max_words"] + 1):
            if len(words) <= k:
                break
            counts[" ".join(words[-k:])] += 1
    markers = [m.lower() for m in FOOTER["footer_markers"]]
    out = []
    for ending, count in counts.items():
        if count < threshold:
            continue
        has_marker = any(m in ending.lower() for m in markers)
        if has_marker or count / n >= FOOTER["footer_share_without_marker"]:
            out.append((ending, count, count / n, has_marker))
    return out


def strip_footers(text, index):
    for _ in range(4):
        tail = " ".join(text.split()[-2:])
        for footer in index.get(tail, ()):
            if text.endswith(footer) and len(text) > len(footer):
                text = text[: -len(footer)].rstrip(" |¦-–—:•·")
                break
        else:
            break
    return text


def clean(text):
    text = URL_RE.sub(" ", text)
    text = HANDLE_RE.sub(" ", text)
    text = text.replace("#", " ")
    text = "".join(ch for ch in text if unicodedata.category(ch) not in DROP_CATEGORIES)
    return " ".join(text.split())


def chunks(text, width=FRAG_CHARS, overlap=FRAG_OVERLAP):
    start = 0
    while start < len(text):
        end = min(start + width, len(text))
        yield text[start:end]
        if end == len(text):
            break
        start = end - overlap


# ------------------------------------------------------------------------------- events
def manifest(slug):
    return json.loads((ROOT / "data/processed" / f"event_{slug}_qwen3_manifest.json").read_text())


def window(slug):
    w = manifest(slug)["window"]
    return date.fromisoformat(w["match_start"]), date.fromisoformat(w["match_end_exclusive"])


def full_window():
    spans = [window(s) for s in EVENTS]
    return min(s for s, _ in spans), max(e for _, e in spans)


# ------------------------------------------------------------------------------ prepare
def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    start, end = full_window()
    archived = M.load_archived_sources()
    con = sqlite3.connect(f"file:{M.NEWS_DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT source, message_id, date, summary, original_message FROM unified_messages "
        "WHERE date >= ? AND date < ?", (start.isoformat(), end.isoformat())).fetchall()
    posts = []
    for source, mid, dt, summary, original in rows:
        if source in archived:
            continue
        text = " ".join(normalize_text(original, None, max_chars=10**9).split())
        posts.append({"source": source, "message_id": str(mid), "date": dt,
                      "summary": summary or "", "raw": text})
    by_source = collections.defaultdict(list)
    for p in posts:
        if p["raw"]:
            by_source[p["source"]].append(p["raw"])
    footer_rows, all_footers = [], set()
    for source, texts in sorted(by_source.items()):
        for ending, count, share, has_marker in find_footers(texts):
            footer_rows.append([source, len(texts), count, round(share, 3), has_marker, ending])
            all_footers.add(ending)
    index = collections.defaultdict(list)
    for f in sorted(all_footers, key=len, reverse=True):
        index[" ".join(f.split()[-2:])].append(f)
    stripped = 0
    with (OUT / "texts.jsonl").open("w", encoding="utf-8") as f:
        for p in posts:
            body = strip_footers(p["raw"], index)
            stripped += body != p["raw"]
            p["text"] = clean(body)
            del p["raw"]
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with (OUT / "footers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "posts_with_text", "posts_with_ending", "share", "has_marker", "ending"])
        w.writerows(sorted(footer_rows, key=lambda r: (r[0], -r[2])))
    n_frag = sum(len(list(chunks(p["text"]))) for p in posts if p["text"])
    chars = sum(len(c) for p in posts if p["text"] for c in chunks(p["text"]))
    report = {"window": [start.isoformat(), end.isoformat()], "posts": len(posts),
              "posts_with_text": sum(1 for p in posts if p["text"]),
              "posts_with_footer_stripped": stripped, "distinct_footers": len(all_footers),
              "fragments": n_frag, "fragment_chars": chars,
              "estimated_cost_usd_at_3_chars_per_token": round(chars / 3 / 1e6 * PRICE_PER_M, 3)}
    (OUT / "prepare_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


def load_posts():
    with (OUT / "texts.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


# -------------------------------------------------------------------------------- embed
def embed():
    posts = load_posts()
    rows = [(i, c) for i, p in enumerate(posts) if p["text"] for c in chunks(p["text"])]
    folder = OUT / "fragments"
    folder.mkdir(exist_ok=True)
    np.save(folder / "owners.npy", np.array([i for i, _ in rows], np.int32))
    size = 64
    tasks = [(i, [c for _, c in rows[i:i + size]]) for i in range(0, len(rows), size)
             if not (folder / f"part_{i // size:05d}.npy").exists()]
    usage = [json.loads(p.read_text()) for p in folder.glob("part_*.usage.json")]
    spent = [sum(u.get("cost") or u.get("prompt_tokens", 0) / 1e6 * PRICE_PER_M for u in usage)]
    lock = threading.Lock()
    key = M.get_openrouter_key()

    def one(task):
        i, texts = task
        with lock:
            if spent[0] > COST_CAP_USD:
                return "cost cap"
        body = {"model": M.QWEN_MODEL, "input": texts, "encoding_format": "base64",
                "provider": {"order": [M.QWEN_PROVIDER], "allow_fallbacks": False}}
        for attempt in range(6):
            try:
                req = urllib.request.Request(M.QWEN_API_URL, data=json.dumps(body).encode(),
                                             method="POST")
                req.add_header("Authorization", f"Bearer {key}")
                req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=120) as r:
                    result = json.loads(r.read())
                break
            except Exception as error:  # noqa: BLE001 — retried, then reported
                if attempt == 5:
                    return str(error)
                time.sleep(2 ** attempt)
        data = sorted(result["data"], key=lambda r: r["index"])
        X = np.array([np.frombuffer(base64.b64decode(r["embedding"]), dtype="<f4") for r in data],
                     np.float32)
        if len(X) != len(texts):
            return "missing rows"
        X /= np.linalg.norm(X, axis=1, keepdims=True)
        np.save(folder / f"part_{i // size:05d}.npy", X.astype(np.float16))
        u = result.get("usage", {})
        (folder / f"part_{i // size:05d}.usage.json").write_text(json.dumps(u))
        with lock:
            spent[0] += u.get("cost") or u.get("prompt_tokens", 0) / 1e6 * PRICE_PER_M
        return None

    errors = collections.Counter()
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for n, error in enumerate(pool.map(one, tasks), 1):
            if error:
                errors[error[:80]] += 1
            if n % 200 == 0 or n == len(tasks):
                print(f"{n}/{len(tasks)} batches, ${spent[0]:.3f}, errors {dict(errors)}", flush=True)
    if errors:
        raise SystemExit(f"unfinished batches: {dict(errors)}; rerun to resume")


def fragment_matrix():
    folder = OUT / "fragments"
    owners = np.load(folder / "owners.npy")
    parts = [np.load(p) for p in sorted(folder.glob("part_*.npy"))]
    X = np.vstack(parts)
    assert len(X) == len(owners), "fragment index incomplete; rerun embed"
    return owners, X


# -------------------------------------------------------------------------------- score
def score():
    posts = load_posts()
    key_index = {(p["source"], p["message_id"]): i for i, p in enumerate(posts)}
    owners, X = fragment_matrix()
    for slug in EVENTS:
        target = OUT / f"scores_{slug}.json"
        if target.exists():
            continue
        m = manifest(slug)
        event = {"name": m["event"]["name"], "quotes": m["event"]["quotes"]}
        probes = M.build_probes(event)
        Q = M.embed_texts_qwen3(probes)
        start, end = window(slug)
        # fulltext: best fragment, best probe
        per_frag = (X.astype(np.float32) @ Q.T).max(axis=1)
        full = np.full(len(posts), -1.0, np.float32)
        np.maximum.at(full, owners, per_frag)
        # summary: the sidecar on Neo, every post in the window
        _, sims, _, records = M.qwen_retrieve_remote(start, end, Q)
        summ = {}
        for r, s in zip(records, sims):
            i = key_index.get((r["source"], str(r["message_id"])))
            if i is not None:
                summ[i] = float(s)
        lo, hi = start.isoformat(), end.isoformat()
        rows = [{"i": i, "summary": summ[i], "fulltext": float(full[i])}
                for i, p in enumerate(posts)
                if lo <= p["date"][:10] < hi and i in summ and full[i] > -1]
        target.write_text(json.dumps({"slug": slug, "event": event, "probes": probes,
                                      "window": [lo, hi], "rows": rows}))
        print(f"{slug}: {len(rows):,} posts with both scores "
              f"(window posts with text {sum(1 for p in posts if lo <= p['date'][:10] < hi and p['text']):,})")


def ranked(rows, method):
    return [r["i"] for r in sorted(rows, key=lambda r: -r[method])]


# ------------------------------------------------------------------------------ prompts
PROMPT = """Ты проверяешь, сообщает ли новостной пост о конкретном событии из опроса ФОМ.

Событие (так его назвали респонденты на неделе {week}): «{name}»
Как его описывали респонденты: {quotes}
Окно поиска: {lo} — {hi}.

Для каждого поста ниже реши:
- "yes" — пост сообщает об этом событии или обсуждает его (само событие, его ход, реакции на
  него, его прямые последствия);
- "no" — пост о другом, в том числе о похожем событии того же рода (другая катастрофа, другие
  переговоры, другие цены) или упоминает тему лишь мимоходом.
Суди по тексту поста, а не по каналу. Ответ — по одному элементу на каждый id.

Посты:
{posts}
"""


def prompts():
    posts = load_posts()
    folder = OUT / "labels" / "prompts"
    folder.mkdir(parents=True, exist_ok=True)
    schema = {"type": "object", "additionalProperties": False, "required": ["labels"],
              "properties": {"labels": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["id", "label"],
                  "properties": {"id": {"type": "string"},
                                 "label": {"type": "string", "enum": ["yes", "no"]}}}}}}
    (OUT / "labels" / "schema.json").write_text(json.dumps(schema, indent=2))
    total = 0
    for slug in EVENTS:
        s = json.loads((OUT / f"scores_{slug}.json").read_text())
        pool = sorted(set(ranked(s["rows"], "summary")[:TOP]) | set(ranked(s["rows"], "fulltext")[:TOP]))
        rng = np.random.default_rng(17)
        pool = [int(i) for i in rng.permutation(pool)]   # mix the two methods' posts
        m = manifest(slug)["event"]
        for k in range(0, len(pool), SLICE):
            block = "\n\n".join(f"[id {i}] {posts[i]['text'][:2500]}" for i in pool[k:k + SLICE])
            text = PROMPT.format(week=f"{m['year']}-W{m['week']:02d}", name=m["name"],
                                 quotes="; ".join(m["quotes"]), lo=s["window"][0],
                                 hi=s["window"][1], posts=block)
            (folder / f"slice_{slug}_{k // SLICE:03d}.txt").write_text(text, encoding="utf-8")
        total += len(pool)
        print(f"{slug}: {len(pool)} posts to label")
    print(f"total {total} posts")


# ------------------------------------------------------------------------------- report
def load_labels():
    labels = {}
    for p in sorted((OUT / "labels" / "out").glob("slice_*.json")):
        slug = p.stem[len("slice_"):].rsplit("_", 1)[0]
        for item in json.loads(p.read_text())["labels"]:
            labels[(slug, int(item["id"]))] = item["label"] == "yes"
    return labels


def report():
    labels = load_labels()
    results, ks = {}, [50, 100, 200, 300, 500]
    for slug in EVENTS:
        s = json.loads((OUT / f"scores_{slug}.json").read_text())
        order = {m: ranked(s["rows"], m) for m in ("summary", "fulltext")}
        pool = set(order["summary"][:TOP]) | set(order["fulltext"][:TOP])
        missing = [i for i in pool if (slug, i) not in labels]
        relevant = {i for i in pool if labels.get((slug, i))}
        r = {"window_posts": len(s["rows"]), "labelled": len(pool) - len(missing),
             "unlabelled": len(missing), "relevant_in_pool": len(relevant), "methods": {}}
        for method, o in order.items():
            r["methods"][method] = {
                f"@{k}": {"hits": sum(1 for i in o[:k] if i in relevant),
                          "precision": round(sum(1 for i in o[:k] if i in relevant) / k, 3),
                          "recall_of_pool": round(sum(1 for i in o[:k] if i in relevant)
                                                  / max(1, len(relevant)), 3)} for k in ks}
            # where each method puts the posts only the other method found in its top 500
        other_only = {m: [i for i in relevant if i in order[m][:TOP]
                          and i not in order["fulltext" if m == "summary" else "summary"][:TOP]]
                      for m in order}
        r["relevant_only_in_top500_of"] = {m: len(v) for m, v in other_only.items()}
        results[slug] = r
    (HERE / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------------- deep
# The top 500 is mostly on-event for four of the five events, so it cannot tell the methods
# apart where the pipeline works (it used up to 3,000 candidates). Here: the posts that only
# one method puts in its top DEEP, a random sample of DEEP_SAMPLE from each side, labelled
# the same way; the on-event share of each sample, times the side's size, estimates how many
# on-event posts each method finds that the other one misses.
DEEP, DEEP_SAMPLE = 3000, 100


def deep_sets(slug):
    s = json.loads((OUT / f"scores_{slug}.json").read_text())
    top = {m: set(ranked(s["rows"], m)[:DEEP]) for m in ("summary", "fulltext")}
    return s, {"summary": sorted(top["summary"] - top["fulltext"]),
               "fulltext": sorted(top["fulltext"] - top["summary"]), "both": top["summary"] & top["fulltext"]}


def deep_prompts():
    posts = load_posts()
    folder = OUT / "labels" / "prompts"
    for slug in EVENTS:
        s, sets = deep_sets(slug)
        rng = np.random.default_rng(17)
        sample = [int(i) for side in ("summary", "fulltext")
                  for i in rng.choice(sets[side], min(DEEP_SAMPLE, len(sets[side])), replace=False)]
        sample = [int(i) for i in rng.permutation(sample)]
        m = manifest(slug)["event"]
        for k in range(0, len(sample), SLICE):
            block = "\n\n".join(f"[id {i}] {posts[i]['text'][:2500]}" for i in sample[k:k + SLICE])
            text = PROMPT.format(week=f"{m['year']}-W{m['week']:02d}", name=m["name"],
                                 quotes="; ".join(m["quotes"]), lo=s["window"][0],
                                 hi=s["window"][1], posts=block)
            (folder / f"slice_deep_{slug}_{k // SLICE:03d}.txt").write_text(text, encoding="utf-8")
        print(f"{slug}: only-summary {len(sets['summary'])}, only-fulltext {len(sets['fulltext'])}, "
              f"both {len(sets['both'])}; sampled {len(sample)}")


def deep_report():
    labels = load_labels()
    results = json.loads((HERE / "results.json").read_text())
    for slug in EVENTS:
        _, sets = deep_sets(slug)
        r = {"both": len(sets["both"])}
        for side in ("summary", "fulltext"):
            got = [labels[("deep_" + slug, i)] for i in sets[side] if ("deep_" + slug, i) in labels]
            share = sum(got) / len(got) if got else None
            r[f"only_{side}"] = {"posts": len(sets[side]), "sampled": len(got),
                                 "on_event_in_sample": sum(got),
                                 "estimated_on_event": round(share * len(sets[side])) if got else None}
        results[slug]["top3000"] = r
        print(slug, json.dumps(r, ensure_ascii=False))
    (HERE / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["prepare", "embed", "score", "prompts", "report",
                                     "deep_prompts", "deep_report"])
    {"prepare": prepare, "embed": embed, "score": score, "prompts": prompts,
     "report": report, "deep_prompts": deep_prompts,
     "deep_report": deep_report}[ap.parse_args().step]()
