#!/usr/bin/env python3
"""Stage 1: per-message framing extraction over a single-event dataset.

Reads a dataset CSV produced by build_event_dataset.py, normalizes each message, extracts a
structured framing record with gpt-5.5, and writes one JSON object per line to
data/interim/event_<slug>_framing.jsonl.

Resumable (skips message_ids already in the output) and budget-aware (pre-trims the work to fit
a daily token budget, so a partial run + rerun continues cleanly).

Usage:
  python scripts/extract_framing.py --limit 10            # smoke test
  python scripts/extract_framing.py                       # full run (resumes)
  python scripts/extract_framing.py --canonicalize-only   # merge entity names in an existing jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.events_coverage import framing as F
from src.events_coverage.matching import UNCATEGORIZED_LABEL
from src.events_coverage.paths import DATA_INTERIM, DATA_PROCESSED

csv.field_size_limit(10**7)

# Calibrated against the smoke run (~2,890 tok/msg: ~1,050 prompt-in + ~1,075 out + text).
PROMPT_OVERHEAD_TOK = 1050  # fixed system+context input tokens per call
OUTPUT_EST_TOK = 1075       # structured-output (+reasoning) tokens per call
DEFAULT_BUDGET = 950_000    # stay under the 1M/day free tier


def slug_from_path(p: Path) -> str:
    m = re.match(r"event_(.+)_dataset\.(csv|jsonl)$", p.name)
    return m.group(1) if m else p.stem


def estimate_tokens(text: str) -> int:
    # Cyrillic runs ~2.2 chars/token in o200k; add fixed prompt + output overhead.
    return int(len(text) / 2.2) + PROMPT_OVERHEAD_TOK + OUTPUT_EST_TOK


def interleave_by_group(rows: list[dict]) -> list[dict]:
    """Round-robin across media groups so any budget-limited partial stays balanced by group
    (preserves within-group rank order). Resume still eventually covers every message."""
    buckets: dict[str, deque] = defaultdict(deque)
    for r in rows:
        buckets[r.get("media_group")].append(r)
    queues = list(buckets.values())
    out: list[dict] = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.popleft())
    return out


def load_event_context(slug: str) -> tuple[str, str]:
    """Return (event_name, event_desc) from the matching manifest if present."""
    manifest = DATA_PROCESSED / f"event_{slug}_manifest.json"
    if manifest.exists():
        meta = json.loads(manifest.read_text(encoding="utf-8")).get("event", {})
        name = meta.get("name", slug)
        quotes = meta.get("quotes", []) or []
        desc = "; ".join(q.strip("«»\" ") for q in quotes[:5])
        return name, desc
    return slug, ""


def read_done_ids(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done = set()
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            try:
                done.add(str(json.loads(line)["message_id"]))
            except (ValueError, KeyError):
                continue
    return done


def canonicalize_only(out_path: Path) -> None:
    """Post-pass: merge near-duplicate canonical entity names across an existing jsonl in place."""
    client = F.get_openai_client()
    records = [json.loads(line) for line in open(out_path, encoding="utf-8")]
    canon = {e["canonical"] for r in records for e in r.get("entities", []) if e.get("canonical")}
    canon |= {m["entity"] for r in records for m in r.get("moral_evaluation", []) if m.get("entity")}
    mapping = F.canonicalize_entities(client, sorted(canon))
    n_merged = sum(1 for k, v in mapping.items() if k != v)
    for r in records:
        for e in r.get("entities", []):
            e["canonical"] = mapping.get(e.get("canonical"), e.get("canonical"))
        for m in r.get("moral_evaluation", []):
            m["entity"] = mapping.get(m.get("entity"), m.get("entity"))
        ca = r.get("causal_attribution") or {}
        if ca.get("cause_entity"):
            ca["cause_entity"] = mapping.get(ca["cause_entity"], ca["cause_entity"])
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"canonicalized {len(records)} records; merged {n_merged} entity names -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=None,
                    help="dataset CSV (default: the Kursk event dataset)")
    ap.add_argument("--slug", default=None, help="event slug (default: derived from --input)")
    ap.add_argument("--event-name", default=None, help="override event name for the prompt")
    ap.add_argument("--limit", type=int, default=None, help="process at most N messages")
    ap.add_argument("--workers", type=int, default=4, help="concurrent extraction calls")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="token budget for this run")
    ap.add_argument("--canonicalize", action="store_true",
                    help="run entity-name merge after extraction")
    ap.add_argument("--canonicalize-only", action="store_true",
                    help="only run the entity-name merge over an existing jsonl, then exit")
    args = ap.parse_args()

    input_csv = args.input or (DATA_PROCESSED / "event_kursk_2025w11_dataset.csv")
    slug = args.slug or slug_from_path(input_csv)
    out_path = DATA_INTERIM / f"event_{slug}_framing.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.canonicalize_only:
        canonicalize_only(out_path)
        return

    event_name, event_desc = load_event_context(slug)
    if args.event_name:
        event_name = args.event_name
    print(f"event: «{event_name}»  | dataset: {input_csv.name}  | out: {out_path.name}")

    with open(input_csv, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if r.get("media_group") != UNCATEGORIZED_LABEL]  # drop ungrouped (plan)

    done = read_done_ids(out_path)
    pending = [r for r in rows if str(r["message_id"]) not in done]
    pending = interleave_by_group(pending)  # balance any budget-limited partial across groups
    if args.limit:
        pending = pending[: args.limit]
    print(f"{len(rows)} grouped rows | {len(done)} already done | {len(pending)} pending")

    # Pre-trim to the token budget so the (possibly threaded) run has no mid-flight aborts.
    budgeted, est_total = [], 0
    for r in pending:
        text = F.normalize_text(r.get("original_message"), r.get("summary"))
        tok = estimate_tokens(text)
        if est_total + tok > args.budget:
            break
        est_total += tok
        budgeted.append((r, text))
    if len(budgeted) < len(pending):
        print(f"  budget {args.budget:,} tok -> processing {len(budgeted)}/{len(pending)} now; "
              f"rerun to continue the rest (resume skips done).")

    if not budgeted:
        print("nothing to do.")
        return

    client = F.get_openai_client()
    lock = threading.Lock()
    totals = {"in": 0, "out": 0, "ok": 0, "off": 0, "err": 0}

    def work(item):
        row, text = item
        analysis, usage = F.extract_framing(client, text, event_name, event_desc)
        record = {
            "message_id": str(row["message_id"]), "source": row.get("source"),
            "media_group": row.get("media_group"), "date": row.get("date"),
            "is_digest": row.get("is_digest"), "rerank_score": row.get("rerank_score"),
            "text_used": text, **analysis.model_dump(mode="json"),
        }
        return record, usage

    out_f = open(out_path, "a", encoding="utf-8")
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futures = {ex.submit(work, item): item for item in budgeted}
            for i, fut in enumerate(as_completed(futures), 1):
                row = futures[fut][0]
                try:
                    record, usage = fut.result()
                except Exception as exc:  # noqa: BLE001 - log and continue
                    totals["err"] += 1
                    print(f"  [{i}/{len(budgeted)}] ERROR msg {row.get('message_id')}: "
                          f"{type(exc).__name__}: {exc}")
                    continue
                with lock:
                    out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out_f.flush()
                    totals["in"] += usage.get("in", 0)
                    totals["out"] += usage.get("out", 0)
                    totals["ok"] += 1
                    totals["off"] += 0 if record.get("on_event", True) else 1
                if i % 25 == 0 or i == len(budgeted):
                    print(f"  [{i}/{len(budgeted)}] ok={totals['ok']} off_event={totals['off']} "
                          f"err={totals['err']} tokens={totals['in']+totals['out']:,}")
    finally:
        out_f.close()

    print(f"\ndone: {totals['ok']} extracted ({totals['off']} flagged off-event), "
          f"{totals['err']} errors. tokens used ~{totals['in']+totals['out']:,} "
          f"(in {totals['in']:,} / out {totals['out']:,}). -> {out_path}")

    if args.canonicalize and totals["ok"]:
        canonicalize_only(out_path)


if __name__ == "__main__":
    main()
