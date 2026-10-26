#!/usr/bin/env python
"""Steps of the ten-event test. Paid steps add their spend to data/interim/ten_events_readers/spend.jsonl
and refuse to start once it passes ten.CAP_USD. Every step is resumable.

New events only (the three old hold-out events already have all of this):
  prepare         window posts -> <slug>/texts.jsonl: JSON blobs unwrapped, per-channel repeated
                  endings stripped, links, @handles, # and emoji removed (as fulltext_vs_summary)
  embed           paid: 650/120-character fragments -> Qwen3 vectors via OpenRouter
  cosine          paid (cents): probe vectors, full-text cosine of every window post (best fragment)
  brief_prompts   free: event-brief prompts (briefs.PROMPT), answered by codex_answer.sh
  jev             paid: Jev 1.13, question v3, on the 3,000 candidates
  label_prompts   free: 150 random candidates from each of 5 rank bands, run.PROMPT, slices of 50
  label_collect   Codex answers -> holdout_labels/<slug>.json
All ten events:
  reader_prompts  free: the 750 labelled posts per event in slices of 50, run.PROMPT (for the old
                  events these are the same prompts the earlier reader test used)
  deepseek        paid: deepseek/deepseek-v4-flash via OpenRouter (new events only)
  claude MODEL    paid: claude-haiku-5-5 (direct calls) or claude-sonnet-5-5 (Message Batches),
                  effort low, structured JSON output; LIMIT=2 for the cost probe
  reader_collect  answers -> reader_labels/<reader>/<slug>.json
"""
from __future__ import annotations

import collections
import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

import ten as T

R, C = T.R, T.C
from events_coverage import matching as M  # noqa: E402
from events_coverage.framing import normalize_text  # noqa: E402


# ------------------------------------------------------------------------------ prepare
def prepare():
    archived = M.load_archived_sources()
    con = sqlite3.connect(f"file:{M.NEWS_DB}?mode=ro", uri=True)
    for slug in T.NEW:
        target = T.folder(slug) / "texts.jsonl"
        if target.exists():
            continue
        T.folder(slug).mkdir(parents=True, exist_ok=True)
        lo, hi = T.event(slug)["window"]
        rows = con.execute("SELECT source, message_id, date, summary, original_message FROM unified_messages "
                           "WHERE date >= ? AND date < ?", (lo, hi)).fetchall()
        posts = []
        for source, mid, dt, summary, original in rows:
            if source in archived:
                continue
            text = " ".join(normalize_text(original, None, max_chars=10**9).split())
            posts.append({"source": source, "message_id": str(mid), "date": dt, "summary": summary or "", "raw": text})
        by_source = collections.defaultdict(list)
        for p in posts:
            if p["raw"]:
                by_source[p["source"]].append(p["raw"])
        footers = {ending for texts in by_source.values() for ending, *_ in R.find_footers(texts)}
        index = collections.defaultdict(list)
        for f in sorted(footers, key=len, reverse=True):
            index[" ".join(f.split()[-2:])].append(f)
        stripped = 0
        with target.open("w", encoding="utf-8") as f:
            for p in posts:
                body = R.strip_footers(p["raw"], index)
                stripped += body != p["raw"]
                p["text"] = R.clean(body)
                del p["raw"]
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        report = {"window": [lo, hi], "posts": len(posts), "posts_with_text": sum(1 for p in posts if p["text"]),
                  "sources": len({p["source"] for p in posts}), "posts_with_footer_stripped": stripped,
                  "distinct_footers": len(footers),
                  "fragments": sum(len(list(R.chunks(p["text"]))) for p in posts if p["text"])}
        (T.folder(slug) / "prepare_report.json").write_text(json.dumps(report, indent=2))
        print(slug, json.dumps(report), flush=True)


# -------------------------------------------------------------------------------- embed
def _in_window_folder(slug, fn):
    """run.py's embed/fragment_matrix read run.OUT; point it at this event's folder."""
    saved = R.OUT
    R.OUT = T.folder(slug)
    try:
        return fn()
    finally:
        R.OUT = saved


def embed():
    for slug in T.NEW:
        folder = T.folder(slug) / "fragments"
        if (folder / "done").exists():
            continue
        T.guard()
        before = {p.name for p in folder.glob("part_*.usage.json")} if folder.exists() else set()
        try:
            _in_window_folder(slug, R.embed)
        finally:
            new = [p for p in folder.glob("part_*.usage.json") if p.name not in before]
            usd = sum((json.loads(p.read_text()).get("cost") or
                       json.loads(p.read_text()).get("prompt_tokens", 0) / 1e6 * R.PRICE_PER_M) for p in new)
            tokens = sum(json.loads(p.read_text()).get("prompt_tokens", 0) for p in new)
            T.book("embed", usd, slug=slug, batches=len(new), input_tokens=tokens)
            print(f"{slug}: {len(new)} batches, {tokens:,} tokens, ${usd:.4f}; ledger ${T.spent():.3f}", flush=True)
        (folder / "done").write_text("ok")


# ------------------------------------------------------------------------------- cosine
def cosine():
    for slug in T.NEW:
        target = T.scores_path(slug)
        if target.exists():
            continue
        T.guard()
        posts = T.posts(slug)
        owners, X = _in_window_folder(slug, R.fragment_matrix)
        e = T.event(slug)
        probes = M.build_probes({"name": e["name"], "quotes": e["quotes"]})
        Q = M.embed_texts_qwen3(probes).astype(np.float32)
        per_frag = np.concatenate([(X[k:k + 20000].astype(np.float32) @ Q.T).max(axis=1)
                                   for k in range(0, len(X), 20000)])
        full = np.full(len(posts), -1.0, np.float32)
        np.maximum.at(full, owners, per_frag)
        rows = [{"i": i, "fulltext": float(full[i])} for i in range(len(posts)) if full[i] > -1]
        target.write_text(json.dumps({"slug": slug, "probes": probes, "window": e["window"], "rows": rows}))
        T.book("cosine", 0.0001, slug=slug, probes=len(probes))
        print(f"{slug}: {len(rows):,} window posts with text, {len(probes)} probes", flush=True)


# ------------------------------------------------------------------------------- briefs
def brief_prompts():
    import briefs as B
    folder = T.OUT / "briefs" / "prompts"
    folder.mkdir(parents=True, exist_ok=True)
    (T.OUT / "briefs" / "schema.json").write_text((C.OUT / "briefs" / "schema.json").read_text())
    for slug in T.NEW:
        posts, e = T.posts(slug), T.event(slug)
        block = "\n\n".join(f"[{posts[i]['date'][:10]}] {posts[i]['text'][:500]}" for i in T.ranked(slug, 40))
        (folder / f"{slug}.txt").write_text(B.PROMPT.format(
            name=e["name"], week=e["week"], quotes="; ".join(e["quotes"]), lo=e["window"][0],
            hi=e["window"][1], posts=block), encoding="utf-8")
        print(slug)


# ---------------------------------------------------------------------------------- jev
def jev():
    import calls as K
    key = M.get_openrouter_key()
    for slug in T.NEW:
        target = T.OUT / "jev" / f"{slug}.json"
        if target.exists():
            continue
        T.guard()
        if T.brief(slug) is None:
            raise SystemExit(f"{slug}: no event brief yet; run brief_prompts and codex_answer.sh")
        posts, ids, q = T.posts(slug), T.ranked(slug), T.question(slug)
        partial = T.OUT / "jev" / f"{slug}.partial.jsonl"
        partial.parent.mkdir(parents=True, exist_ok=True)
        have = {json.loads(l)["i"]: json.loads(l) for l in partial.read_text().splitlines()} if partial.exists() else {}
        todo = [i for i in ids if i not in have]
        lock, paid = threading.Lock(), {"usd": 0.0, "tokens": 0}

        def one(i):   # each answer is saved as it arrives: a crash loses no billed call
            answers, usage = K.ask_jev(key, {"v3": q}, posts[i]["text"][:T.POST_CHARS])
            row = {"i": i, "answer": answers["v3"], "usage": usage}
            with lock:
                with partial.open("a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                paid["tokens"] += usage.get("input_tokens", 0)
                paid["usd"] += usage.get("cost", 0) or usage.get("input_tokens", 0) * K.JEV_PRICE_PER_M / 1e6

        try:
            with ThreadPoolExecutor(12) as pool:
                list(pool.map(one, todo))
        finally:
            T.book("jev", paid["usd"], slug=slug, posts=len(todo), input_tokens=paid["tokens"])
            print(f"{slug}: {len(todo)} posts, {paid['tokens']:,} tokens, ${paid['usd']:.4f}; "
                  f"ledger ${T.spent():.3f}", flush=True)
        rows = {json.loads(l)["i"]: json.loads(l) for l in partial.read_text().splitlines()}
        target.write_text(json.dumps({
            "slug": slug, "variant": "v3", "model": K.JEV_MODEL, "date": time.strftime("%Y-%m-%d"), "question": q,
            "p": {str(i): round(float(C.p_on_event(rows[i]["answer"])), 4) for i in ids},
            "answers": {str(i): rows[i]["answer"] for i in ids}}, ensure_ascii=False))


# ------------------------------------------------------------------------------- labels
BANDS = [(0, 150), (150, 500), (500, 1000), (1000, 2000), (2000, 3000)]
PER_BAND = 150
LAB = T.OUT / "holdout_labelling"


def sample(slug):
    """Same draw as jev_selection/holdout_labels.py: seed 17, 150 per rank band."""
    ranked = T.ranked(slug)
    rng = np.random.default_rng(17)
    picked, weight = [], {}
    for lo, hi in BANDS:
        band = ranked[lo:hi]
        for t in rng.choice(len(band), size=min(PER_BAND, len(band)), replace=False):
            picked.append(band[t]); weight[band[t]] = len(band) / min(PER_BAND, len(band))
    return picked, weight


def _slices(slug, ids, folder):
    posts, e = T.posts(slug), T.event(slug)
    ids = [int(i) for i in np.random.default_rng(5).permutation(ids)]
    for k in range(0, len(ids), R.SLICE):
        block = "\n\n".join(f"[id {i}] {posts[i]['text'][:T.POST_CHARS]}" for i in ids[k:k + R.SLICE])
        text = R.PROMPT.format(week=e["week"], name=e["name"], quotes="; ".join(e["quotes"]),
                               lo=e["window"][0], hi=e["window"][1], posts=block)
        (folder / f"{slug}_{k // R.SLICE:03d}.txt").write_text(text, encoding="utf-8")


def label_prompts():
    (LAB / "prompts").mkdir(parents=True, exist_ok=True)
    (LAB / "schema.json").write_text((R.OUT / "labels" / "schema.json").read_text())
    for slug in T.NEW:
        ids, _ = sample(slug)
        _slices(slug, ids, LAB / "prompts")
        print(f"{slug}: {len(ids)} posts")


def label_collect():
    (T.OUT / "holdout_labels").mkdir(exist_ok=True)
    for slug in T.NEW:
        ids, weight = sample(slug)
        labels = {}
        for p in sorted((LAB / "out").glob(f"{slug}_*.json")):
            for item in json.loads(p.read_text())["labels"]:
                labels[int(str(item["id"]).strip())] = item["label"] == "yes"
        missing = [i for i in ids if i not in labels]
        if missing:
            print(f"{slug}: {len(missing)} posts unlabelled; rerun codex_answer.sh"); continue
        (T.OUT / "holdout_labels" / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "labeller": "gpt-6.1-sol via codex exec, reasoning medium", "bands": BANDS,
            "labels": {str(i): labels[i] for i in ids}, "weights": {str(i): weight[i] for i in ids}}))
        on = sum(weight[i] for i in ids if labels[i])
        print(f"{slug}: {sum(labels[i] for i in ids)} of {len(ids)} labelled on-event; "
              f"estimated {on:.0f} of 3,000 candidates")


# ------------------------------------------------------------------------------ readers
RD = T.OUT / "reader_labelling"
READERS = {"deepseek-v4-flash": "deepseek/deepseek-v4-flash",
           "claude-haiku-5-5": "claude-haiku-5-5", "claude-sonnet-5-5": "claude-sonnet-5-5"}
# list prices per 1M tokens (input, output); the batch API halves them
CLAUDE_PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}


def reader_prompts():
    (RD / "prompts").mkdir(parents=True, exist_ok=True)
    for slug in T.EVENTS:
        try:
            ids = sorted(T.labels(slug)[0])
        except FileNotFoundError:
            print(f"{slug}: no reference labels yet, skipped"); continue
        _slices(slug, ids, RD / "prompts")
        print(f"{slug}: {len(ids)} posts")


def _todo(name, slugs):
    out = RD / "out" / name
    out.mkdir(parents=True, exist_ok=True)
    todo = [p for p in sorted((RD / "prompts").glob("*.txt"))
            if p.stem.rsplit("_", 1)[0] in slugs and not (out / f"{p.stem}.json").exists()]
    return out, todo[:int(os.environ.get("LIMIT", 10**6))]


def deepseek():
    import reader_calls as RC
    key = M.get_openrouter_key()
    T.guard()
    out, todo = _todo("deepseek-v4-flash", list(T.NEW))
    done = []

    def one(p):
        ans, paid = RC.ask(key, RC.MODELS["deepseek-v4-flash"], p.read_text(encoding="utf-8"))
        done.append(paid)
        if ans is None:
            print(f"{p.stem} FAILED {paid['error']}", flush=True)
        else:
            (out / f"{p.stem}.json").write_text(json.dumps({**ans, "usage": paid["usage"]}, ensure_ascii=False))

    try:
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(one, todo))
    finally:
        cost = sum(d["cost"] for d in done)
        T.book("reader", cost, model=READERS["deepseek-v4-flash"], prompts=len(done),
               input_tokens=sum(d["prompt_tokens"] for d in done),
               output_tokens=sum(d["completion_tokens"] for d in done))
        print(f"deepseek: {len(done)} of {len(todo)} prompts, ${cost:.4f}; ledger ${T.spent():.3f}", flush=True)


def _claude():
    import anthropic
    from dotenv import load_dotenv
    load_dotenv(T.ROOT / ".env")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY_tests"], max_retries=4)


def _params(model, text):
    schema = json.loads((R.OUT / "labels" / "schema.json").read_text())
    return {"model": model, "max_tokens": 16000, "messages": [{"role": "user", "content": text}],
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}}}


def _usd(model, usage, batch):
    pin, pout = CLAUDE_PRICE[model]
    usd = (usage.input_tokens * pin + usage.output_tokens * pout) / 1e6
    return usd / 2 if batch else usd


def _keep(out, stem, msg, model, batch):
    """Save one answer if it covers every id of its prompt; returns (usd, ok)."""
    usd = _usd(model, msg.usage, batch)
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens, "cost": usd,
             "batch": batch, "stop_reason": msg.stop_reason}
    want = {int(x) for x in re.findall(r"\[id (\d+)\]", (RD / "prompts" / f"{stem}.txt").read_text())}
    try:
        ans = json.loads(next(b.text for b in msg.content if b.type == "text"))
        got = {int(str(x["id"]).strip()) for x in ans["labels"] if str(x["id"]).strip().isdigit()}
    except (StopIteration, ValueError, KeyError, TypeError):
        print(f"{stem}: unreadable answer ({msg.stop_reason})", flush=True)
        return usd, usage, False
    if not want <= got:
        print(f"{stem}: answer covers {len(want & got)} of {len(want)} ids", flush=True)
        return usd, usage, False
    (out / f"{stem}.json").write_text(json.dumps({**ans, "usage": usage}, ensure_ascii=False))
    return usd, usage, True


def claude(name):
    T.guard()
    client = _claude()
    out, todo = _todo(name, T.EVENTS)
    if not todo:
        print("nothing to do"); return
    model = READERS[name]
    if name == "claude-haiku-5-5":
        lock, paid = threading.Lock(), {"usd": 0.0, "in": 0, "out": 0, "n": 0}

        def one(p):
            msg = client.messages.create(**_params(model, p.read_text(encoding="utf-8")))
            usd, usage, _ = _keep(out, p.stem, msg, model, False)
            with lock:
                paid["usd"] += usd; paid["in"] += usage["input_tokens"]; paid["out"] += usage["output_tokens"]
                paid["n"] += 1

        try:
            with ThreadPoolExecutor(6) as pool:
                list(pool.map(one, todo))
        finally:
            T.book("reader", paid["usd"], model=model, prompts=paid["n"], input_tokens=paid["in"],
                   output_tokens=paid["out"])
            print(f"{name}: {paid['n']} prompts, {paid['in']:,} in / {paid['out']:,} out, ${paid['usd']:.4f}; "
                  f"ledger ${T.spent():.3f}", flush=True)
        return
    # Sonnet through the Message Batches API: submit, record the batch id, collect when ended
    state = RD / f"batch_{name}.json"
    if not state.exists():
        batch = client.messages.batches.create(requests=[
            {"custom_id": p.stem, "params": _params(model, p.read_text(encoding="utf-8"))} for p in todo])
        state.write_text(json.dumps({"id": batch.id, "prompts": [p.stem for p in todo]}))
        print(f"submitted batch {batch.id} with {len(todo)} prompts", flush=True)
    sid = json.loads(state.read_text())["id"]
    while (b := client.messages.batches.retrieve(sid)).processing_status != "ended":
        print(f"batch {sid}: {b.request_counts}", flush=True)
        time.sleep(60)
    paid = {"usd": 0.0, "in": 0, "out": 0, "n": 0}
    for res in client.messages.batches.results(sid):
        if res.result.type != "succeeded":
            print(f"{res.custom_id}: {res.result.type}", flush=True); continue
        usd, usage, _ = _keep(out, res.custom_id, res.result.message, model, True)
        paid["usd"] += usd; paid["in"] += usage["input_tokens"]; paid["out"] += usage["output_tokens"]; paid["n"] += 1
    T.book("reader", paid["usd"], model=model, prompts=paid["n"], input_tokens=paid["in"],
           output_tokens=paid["out"], batch=sid)
    state.rename(state.with_suffix(".collected.json"))
    print(f"{name}: {paid['n']} prompts, {paid['in']:,} in / {paid['out']:,} out, ${paid['usd']:.4f}; "
          f"ledger ${T.spent():.3f}", flush=True)


def reader_collect():
    for name, model in READERS.items():
        target = T.OUT / "reader_labels" / name
        target.mkdir(parents=True, exist_ok=True)
        for slug in T.EVENTS:
            src = RD / "out" / name
            if name == "deepseek-v4-flash" and slug in T.OLD:
                src = C.OUT / "reader_labelling" / "out" / name
            ids = sorted(T.labels(slug)[0])
            labels, usage = {}, {"cost": 0.0, "input_tokens": 0, "output_tokens": 0}
            for p in sorted(src.glob(f"{slug}_[0-9][0-9][0-9].json")):
                d = json.loads(p.read_text())
                u = d["usage"]
                usage["cost"] += u.get("cost", 0) or 0
                usage["input_tokens"] += u.get("input_tokens", u.get("prompt_tokens", 0)) or 0
                usage["output_tokens"] += u.get("output_tokens", u.get("completion_tokens", 0)) or 0
                for item in d["labels"]:
                    if str(item["id"]).strip().isdigit():   # DeepSeek now and then adds a junk item
                        labels[int(str(item["id"]).strip())] = item["label"] == "yes"
            missing = [i for i in ids if i not in labels]
            (target / f"{slug}.json").write_text(json.dumps({
                "slug": slug, "reader": model, "prompt": "run.PROMPT, slices of 50", "date": time.strftime("%Y-%m-%d"),
                "usage": usage, "missing": missing, "labels": {str(i): labels[i] for i in ids if i in labels}}))
            print(f"{name} {slug}: {len(ids) - len(missing)} of {len(ids)} labelled, ${usage['cost']:.4f}")


if __name__ == "__main__":
    step = sys.argv[1]
    if step == "claude":
        claude(sys.argv[2])
    else:
        {"prepare": prepare, "embed": embed, "cosine": cosine, "brief_prompts": brief_prompts, "jev": jev,
         "label_prompts": label_prompts, "label_collect": label_collect, "reader_prompts": reader_prompts,
         "deepseek": deepseek, "reader_collect": reader_collect}[step]()
