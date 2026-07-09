#!/usr/bin/env python
"""Backfill Qwen3-Embedding-8B vectors for the news corpus via OpenRouter.

From-scratch embedding of message summaries into a float16 **sidecar** store.
The news DB is opened READ-ONLY and never modified.

Design notes
------------
- Model: ``qwen/qwen3-embedding-8b`` (OpenRouter, OpenAI-compatible /embeddings).
- Provider is PINNED (default DeepInfra) so every vector comes from one inference
  stack -> a single consistent space. DeepInfra/Nebius are $0.01/M; SiliconFlow is $0.04/M.
- Output dim defaults to native 4096 (output width is free — you only pay for input
  tokens — so we keep full width and truncate+renorm downstream as needed).
- Vectors come back L2-normalized; we store them as-is in float16.
- Resumable: rows are emitted in a deterministic order; the sidecar is append-only and
  the run skips however many rows are already written.

Safety
------
- Default mode is a 1,000-row DRY RUN (~$0.01). The full corpus requires ``--all``.
- Stops on the first hard error after writing a clean checkpoint.

Sidecar layout (``--out`` dir)
------------------------------
- ``vectors.f16``  : raw little-endian float16, row-major, shape (N, dim)
- ``index.tsv``    : one row per vector — ``message_id<TAB>source<TAB>date`` (lockstep)
- ``manifest.json``: model, provider, dim, params, counts, token spend
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "news_data" / "ask_media_unified_messages_20260604.db"
DEFAULT_OUT = ROOT / "data" / "processed" / "qwen3emb_8b"
API_URL = "https://openrouter.ai/api/v1/embeddings"
MODEL = "qwen/qwen3-embedding-8b"


# --------------------------------------------------------------------------- selection
def build_query(target: str) -> str:
    """Deterministic row order so the append-only sidecar is resumable."""
    base = (
        "SELECT message_id, source, date, summary FROM unified_messages "
        "WHERE summary IS NOT NULL AND length(trim(summary)) > 0 "
    )
    if target == "missing":  # only rows that lack a (Cohere) embedding today
        base += "AND (embedding NOT LIKE '[%' OR embedding IS NULL) "
    # 'all-summary' (default) re-embeds the whole corpus from scratch
    return base + "ORDER BY date, message_id"


def count_rows(con: sqlite3.Connection, target: str) -> int:
    q = build_query(target).replace(
        "SELECT message_id, source, date, summary", "SELECT COUNT(*)"
    )
    q = q.split(" ORDER BY ")[0]
    return con.execute(q).fetchone()[0]


# ------------------------------------------------------------------------------- api
def embed_batch(texts, key, provider, dim, max_retries=6):
    body = {"model": MODEL, "input": texts}
    if dim:
        body["dimensions"] = dim
    if provider:
        body["provider"] = {"order": [provider], "allow_fallbacks": False}
    payload = json.dumps(body).encode()
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(API_URL, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Title", "events-coverage-backfill")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read())
            data = sorted(resp["data"], key=lambda d: d["index"])  # realign to input order
            vecs = np.asarray([d["embedding"] for d in data], dtype=np.float32)
            tokens = (resp.get("usage") or {}).get("prompt_tokens", 0)
            return vecs, tokens
        except urllib.error.HTTPError as e:
            transient = e.code in (429, 500, 502, 503, 504)
            if transient and attempt < max_retries:
                wait = min(60.0, 2.0**attempt)
                print(f"    {e.code} on batch; retry {attempt + 1} in {wait:.0f}s", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < max_retries:
                wait = min(60.0, 2.0**attempt)
                print(f"    network error ({e}); retry {attempt + 1} in {wait:.0f}s", flush=True)
                time.sleep(wait)
                continue
            raise


# ------------------------------------------------------------------------------ sidecar
def resume_offset(out: Path, dim: int) -> int:
    idx, vec = out / "index.tsv", out / "vectors.f16"
    if not idx.exists() or not vec.exists():
        return 0
    n_idx = sum(1 for _ in idx.open(encoding="utf-8"))
    n_vec = vec.stat().st_size // (dim * 2)
    if n_idx != n_vec:
        sys.exit(
            f"ERROR: sidecar out of sync (index={n_idx} rows, vectors={n_vec} rows). "
            "Inspect/repair before resuming so records and vectors stay aligned."
        )
    return n_idx


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--target", choices=["all-summary", "missing"], default="all-summary",
                    help="all-summary: re-embed every summary (from scratch); missing: only un-embedded rows")
    ap.add_argument("--provider", default="DeepInfra", help="pinned OpenRouter provider ('' to allow routing)")
    ap.add_argument("--dim", type=int, default=4096, help="output dimension (4096 native; truncates via MRL)")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent in-flight requests (I/O-bound; the embed compute is remote)")
    ap.add_argument("--limit", type=int, default=1000, help="dry-run cap; ignored with --all")
    ap.add_argument("--all", action="store_true", help="process the ENTIRE selection (real spend)")
    args = ap.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY not set (.env or env).")

    args.out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    total = count_rows(con, args.target)
    target_n = total if args.all else min(args.limit, total)
    done = resume_offset(args.out, args.dim)
    mode = "FULL" if args.all else f"DRY-RUN (limit {args.limit})"
    print(f"mode={mode}  target={args.target}  selection={total:,} rows  "
          f"already_done={done:,}  to_process={max(0, target_n - done):,}")
    print(f"model={MODEL}  provider={args.provider or 'auto'}  dim={args.dim}  batch={args.batch_size}")
    if done >= target_n:
        print("nothing to do (already at/over target).")
        return

    vec_f = (args.out / "vectors.f16").open("ab")
    idx_f = (args.out / "index.tsv").open("a", encoding="utf-8")

    sql = build_query(args.target) + f" LIMIT {target_n - done} OFFSET {done}"
    written, tokens_total = done, 0
    t0 = time.time()

    def batches():
        """Yield (texts, meta) chunks by streaming the cursor (single-threaded DB read)."""
        texts, meta = [], []
        for row in con.execute(sql):
            texts.append(row["summary"])
            meta.append((row["message_id"], row["source"], row["date"]))
            if len(texts) >= args.batch_size:
                yield texts, meta
                texts, meta = [], []
        if texts:
            yield texts, meta

    def write_result(vecs, meta):
        nonlocal written
        if vecs.shape[1] != args.dim:
            sys.exit(f"ERROR: provider returned dim {vecs.shape[1]}, expected {args.dim}.")
        vec_f.write(vecs.astype(np.float16).tobytes())
        for mid, src, dt in meta:
            idx_f.write(f"{mid}\t{src}\t{dt}\n")
        vec_f.flush(); idx_f.flush()
        written += len(meta)

    # Concurrency is I/O-bound (the embedding compute runs on the remote provider).
    # Process in ordered "waves": submit `workers` batches, then write their results
    # in submission order so the append-only sidecar stays a clean, resumable prefix.
    gen = batches()
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            while True:
                wave = list(itertools.islice(gen, max(1, args.workers)))
                if not wave:
                    break
                futs = [ex.submit(embed_batch, t, key, args.provider, args.dim) for t, _ in wave]
                for (_, meta), fut in zip(wave, futs):
                    vecs, tok = fut.result()  # raises after retries; earlier batches already flushed
                    write_result(vecs, meta)
                    tokens_total += tok
                rate = (written - done) / max(1e-9, time.time() - t0)
                cost = tokens_total / 1e6 * 0.01
                print(f"  {written:,}/{target_n:,}  ~{rate:.0f} rows/s  spend≈${cost:.4f}", flush=True)
    finally:
        vec_f.close(); idx_f.close(); con.close()

    manifest = {
        "model": MODEL, "provider": args.provider, "dim": args.dim,
        "normalized": True, "dtype": "float16", "target": args.target,
        "rows_written": written, "tokens_spent": tokens_total,
        "est_cost_usd": round(tokens_total / 1e6 * 0.01, 4),
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\ndone: {written:,} rows in sidecar  spend≈${manifest['est_cost_usd']}  -> {args.out}")


if __name__ == "__main__":
    main()
