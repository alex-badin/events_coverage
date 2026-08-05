#!/usr/bin/env python3
"""Build a single-event news dataset via cosine retrieval + Cohere rerank.

Default configuration targets the FOM week-11 2025 event
«Военные действия в Курской области» (recapture of Sudzha).

Usage:
    python scripts/build_event_dataset.py                 # full pipeline (needs COHERE_API_KEY)
    python scripts/build_event_dataset.py --space-check-only
    python scripts/build_event_dataset.py --no-space-check --top-k 1500 --rerank-threshold 0.5

The news database is only ever read (read-only SQLite connection).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from events_coverage.matching import (  # noqa: E402
    EMBED_INPUT_TYPE,
    EMBED_MODEL,
    QWEN_DIM,
    QWEN_MODEL,
    RERANK_MODEL,
    build_probes,
    cosine_topk,
    count_keyword_window,
    embed_texts,
    embed_texts_qwen3,
    get_cohere_client,
    iso_week_window,
    keyword_match,
    load_archived_sources,
    load_defaults,
    load_event,
    load_media_groups,
    load_window_messages,
    media_group_for,
    qwen_retrieve_remote,
    sample_keyword_embedded,
)
from events_coverage.paths import DATA_PROCESSED  # noqa: E402

DEFAULT_EVENT = "Военные действия в Курской области"
CANDIDATE_INPUT_TYPES = ["clustering", "search_document", "search_query", "classification"]


def hist(scores: np.ndarray, bins: int = 10, lo: float = 0.0, hi: float = 1.0) -> str:
    if len(scores) == 0:
        return "  (no scores)"
    edges = np.linspace(lo, hi, bins + 1)
    counts, _ = np.histogram(np.clip(scores, lo, hi), bins=edges)
    width = max(counts.max(), 1)
    lines = []
    for i, c in enumerate(counts):
        bar = "#" * int(round(40 * c / width))
        lines.append(f"  [{edges[i]:.2f},{edges[i + 1]:.2f}) {c:6d} {bar}")
    return "\n".join(lines)


def run_space_check(client, start, end, limit=8, threshold=0.90):
    """Re-embed sample summaries and compare to their STORED vectors.

    Confirms (empirically) which Cohere input_type reproduces the stored document
    embeddings, since the generation code is not on disk. Tests the expected
    `clustering` type first and only probes alternatives if it underperforms, to
    keep API usage minimal. Returns the input_type to use for query embedding.
    """
    records, stored = sample_keyword_embedded(start, end, limit=limit)
    if not records:
        print("  space-check: no keyword-matching embedded summaries found in window; skipping.")
        return EMBED_INPUT_TYPE
    summaries = [r["summary"] for r in records]

    def mean_cosine(itype: str) -> float:
        reembedded = embed_texts(client, summaries, input_type=itype)
        return float(np.sum(reembedded * stored, axis=1).mean())  # both L2-normalized

    print(f"  re-embedding {len(summaries)} sample summaries; cosine vs stored vector:")
    primary = mean_cosine(EMBED_INPUT_TYPE)
    print(f"    input_type={EMBED_INPUT_TYPE:16s} mean={primary:.4f}")
    if primary >= threshold:
        print(f"  -> confirms input_type={EMBED_INPUT_TYPE!r} reproduces stored vectors [OK]")
        return EMBED_INPUT_TYPE

    print("    below threshold — probing alternative input types to diagnose ...")
    best_type, best_mean = EMBED_INPUT_TYPE, primary
    for itype in CANDIDATE_INPUT_TYPES:
        if itype == EMBED_INPUT_TYPE:
            continue
        mc = mean_cosine(itype)
        print(f"    input_type={itype:16s} mean={mc:.4f}")
        if mc > best_mean:
            best_mean, best_type = mc, itype
    verdict = (
        "OK" if best_mean >= threshold else "WARNING: low — field/model assumptions may differ"
    )
    print(f"  -> best input_type={best_type!r} (mean cosine {best_mean:.4f}) [{verdict}]")
    return best_type


def resolve_window(args: argparse.Namespace):
    """(match_start, match_end, monday, sunday, days_before, days_after) from args + config."""
    defaults = load_defaults()
    db = (
        args.days_before
        if args.days_before is not None
        else int(defaults.get("event_window_days_before", 3))
    )
    da = (
        args.days_after
        if args.days_after is not None
        else int(defaults.get("event_window_days_after", 10))
    )
    match_start, match_end, monday, sunday = iso_week_window(args.year, args.week, db, da)
    return match_start, match_end, monday, sunday, db, da


def write_outputs(df, event, win, models, params, base_counts, args) -> pd.DataFrame:
    """(Re)write all derived outputs from a candidates frame at args.rerank_threshold.

    `base_counts` (embedded_pool, keyword_full_window, keyword_embedded_pool) are
    threshold-independent, so this is reusable for free re-thresholding via --from-candidates.
    """
    match_start, match_end, monday, sunday, days_before, days_after = win
    df = df.sort_values("rerank_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    df["kept"] = df["rerank_score"] >= args.rerank_threshold
    kept = df[df["kept"]].copy()

    cand_kw = int(df["keyword_match"].sum())
    kept_kw = int(kept["keyword_match"].sum())
    kept_semantic = int((~kept["keyword_match"]).sum())
    pool_kw = base_counts.get("keyword_embedded_pool")
    retention = (kept_kw / pool_kw) if pool_kw else None

    print("\n[metrics]")
    if base_counts.get("embedded_pool"):
        print(f"    embedded pool ............ {base_counts['embedded_pool']:,}")
    if base_counts.get("keyword_full_window"):
        print(
            f"    keyword hits (full window) {base_counts['keyword_full_window']:,}  "
            "(incl. non-embedded)"
        )
    if pool_kw:
        print(f"    keyword hits (embedded) .. {pool_kw:,}  (noisy superset, not ground truth)")
    print(f"    candidates (reranked) .... {len(df):,}  (keyword among them: {cand_kw:,})")
    n_src = kept["source"].nunique()
    print(f"    KEPT (rerank>={args.rerank_threshold}) ...... {len(kept):,}  | sources={n_src}")
    print(f"      - keyword-bearing {kept_kw:,}; semantic-only {kept_semantic:,}")
    if retention is not None:
        print(f"      - keyword-pool retention . {retention:.1%}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = args.slug
    p_cand = out_dir / f"event_{slug}_candidates.csv"
    p_data = out_dir / f"event_{slug}_dataset.csv"
    p_jsonl = out_dir / f"event_{slug}_dataset.jsonl"
    p_review = out_dir / f"event_{slug}_review_sample.csv"
    p_manifest = out_dir / f"event_{slug}_manifest.json"

    df.to_csv(p_cand, index=False, encoding="utf-8")
    kept.drop(columns=["kept"]).to_csv(p_data, index=False, encoding="utf-8")
    kept.drop(columns=["kept"]).to_json(p_jsonl, orient="records", lines=True, force_ascii=False)

    review_cols = [
        "rank",
        "source",
        "media_group",
        "date",
        "cosine_max",
        "rerank_score",
        "keyword_match",
        "kept",
        "summary",
    ]
    top = df.head(50)
    near = df[
        (df["rerank_score"] >= args.rerank_threshold - 0.1)
        & (df["rerank_score"] < args.rerank_threshold + 0.1)
    ].head(30)
    review = pd.concat([top, near]).drop_duplicates("rank")[review_cols]
    review.to_csv(p_review, index=False, encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "event": {
            "name": event["name"],
            "year": args.year,
            "week": args.week,
            "fom_percentage": event["percentage"],
            "quotes": event["quotes"],
        },
        "window": {
            "match_start": str(match_start),
            "match_end_exclusive": str(match_end),
            "iso_week": [str(monday), str(sunday)],
            "days_before": days_before,
            "days_after": days_after,
        },
        "models": models,
        "params": {**params, "rerank_threshold": args.rerank_threshold},
        "counts": {
            **base_counts,
            "candidates": len(df),
            "kept": len(kept),
            "kept_keyword": kept_kw,
            "kept_semantic_only": kept_semantic,
            "keyword_pool_retention": retention,
        },
        "outputs": {
            "dataset_csv": p_data.name,
            "dataset_jsonl": p_jsonl.name,
            "candidates_csv": p_cand.name,
            "review_sample_csv": p_review.name,
        },
    }
    p_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[wrote]")
    for p in (p_data, p_jsonl, p_cand, p_review, p_manifest):
        print(f"    {p}")
    return kept


def build_dataset(args: argparse.Namespace) -> None:
    win = resolve_window(args)
    match_start, match_end, monday, sunday, days_before, days_after = win
    event = load_event(args.year, args.week, args.event)
    probes = build_probes(event)

    print("=" * 78)
    print(
        f"Event   : {event['name']}  (FOM {args.year} W{args.week}, share={event['percentage']}%)"
    )
    print(f"ISO week : {monday} .. {sunday}")
    print(f"Window   : [{match_start}, {match_end})  (-{days_before}d / +{days_after}d)")
    print(f"Probes   : {len(probes)} ({len(event['quotes'])} quotes + name + combined)")
    print("=" * 78)

    client = get_cohere_client()  # still needed: rerank is always Cohere regardless of retriever

    # --- Verification step 1: embedding-space sanity check (cohere retriever only) ----
    # Meaningless for qwen3: there's no input_type ambiguity, and the sidecar's own
    # vectors were already validated directly (norms ~1.0; see validate_sidecar.py).
    input_type = EMBED_INPUT_TYPE
    if args.retriever == "cohere":
        if not args.no_space_check:
            print("\n[0] Embedding-space sanity check")
            input_type = run_space_check(client, match_start, match_end)
            if args.space_check_only:
                return
    elif args.space_check_only:
        print("--space-check-only has no effect for --retriever qwen3 (no ambiguity to check).")
        return

    # --- Load candidate pool + Step 1: cosine retrieval -------------------------------
    if args.retriever == "qwen3":
        print(f"\n[1-2] Embedding {len(probes)} query probes (qwen3 instruct) ...")
        query_matrix = embed_texts_qwen3(probes)
        print("      scoring on Neo (sidecar + dot product stay remote) ...")
        order, max_sim, best_probe, records = qwen_retrieve_remote(
            match_start, match_end, query_matrix, top_k=args.top_k, floor=args.cosine_floor
        )
        if len(records) == 0:
            raise SystemExit("No embedded messages found in window (qwen3 sidecar).")
        print(f"    candidate pool (embedded): {len(records):,} messages, dim={QWEN_DIM}")
    else:
        print("\n[1] Loading embedded messages in window (retriever=cohere) ...")
        records, doc_matrix = load_window_messages(match_start, match_end, require_embedding=True)
        if doc_matrix is None or len(records) == 0:
            raise SystemExit("No embedded messages found in window.")
        print(
            f"    candidate pool (embedded): {len(records):,} messages, dim={doc_matrix.shape[1]}"
        )
        print(
            f"\n[2] Embedding {len(probes)} query probes (input_type={input_type}) "
            "and scoring cosine ..."
        )
        query_matrix = embed_texts(client, probes, input_type=input_type)
        order, max_sim, best_probe = cosine_topk(
            doc_matrix, query_matrix, top_k=args.top_k, floor=args.cosine_floor
        )
    cap = f"top-k={args.top_k}" if args.top_k else "no cap on candidate count"
    print(f"    candidates after {cap} / floor={args.cosine_floor}: {len(order):,}")
    print(f"    cosine (all pool) distribution:\n{hist(max_sim, lo=0.0, hi=0.8)}")

    # --- Text lookup: qwen3 sidecar records carry no text; the Cohere DB read does ----
    if args.retriever == "qwen3":
        all_recs, _ = load_window_messages(match_start, match_end, require_embedding=False)
        text_by_key = {(r["source"], str(r["message_id"])): r for r in all_recs}
        cand = [text_by_key[(records[i]["source"], str(records[i]["message_id"]))] for i in order]
        pool_keys = [(r["source"], str(r["message_id"])) for r in records]
        keyword_embedded_pool = sum(
            keyword_match(text_by_key[k]["summary"], text_by_key[k]["original_message"])
            for k in pool_keys
        )
    else:
        cand = [records[i] for i in order]
        keyword_embedded_pool = int(
            sum(keyword_match(r["summary"], r["original_message"]) for r in records)
        )

    # --- Step 2: rerank (always Cohere rerank-v3.5, embedder-agnostic) ---------------
    #
    # One query per probe, keeping each post's best score — NOT one query made by gluing the
    # event name and all the respondent quotes together. Measured on 2026-08-03 over the
    # 3,000 candidates of the six pilot events: the glued query scores a post lower than any
    # of its parts and reorders the list (Spearman 0.735-0.923 against the per-probe best),
    # so posts unmistakably about the event were dropped. Worst single case: a post about
    # Russian and US diplomats meeting in Istanbul scored 0.867 against the quote
    # «встреча дипмиссий России и США» and 0.327 against the glued query, i.e. excluded.
    # «Рост цен, тарифов» went from 0 kept posts to 27 on the same candidates.
    #
    # The cost is one rerank pass per probe instead of one in total, and a mechanically
    # looser filter: a post now gets len(probes) chances to clear the threshold rather than
    # one. rerank_best_probe records which probe won, so that looseness is auditable.
    docs = [(r["summary"] or r["original_message"] or "") for r in cand]
    from events_coverage.matching import rerank as cohere_rerank

    if args.rerank_mode == "merged":
        rerank_query = f"{event['name']}. " + "; ".join(q.strip('«»" ') for q in event["quotes"])
        print(f"\n[3] Reranking {len(docs):,} candidates with {RERANK_MODEL}, one glued query ...")
        rerank_scores = cohere_rerank(client, rerank_query, docs)
        rerank_best = np.zeros(len(docs), dtype=np.int64)
        rerank_queries = [rerank_query]
    else:
        rerank_queries = probes
        print(
            f"\n[3] Reranking {len(docs):,} candidates with {RERANK_MODEL}, "
            f"{len(rerank_queries)} separate queries, keeping each post's best ..."
        )
        per_query = np.zeros((len(rerank_queries), len(docs)), dtype=np.float32)
        for i, query in enumerate(rerank_queries):
            per_query[i] = cohere_rerank(client, query, docs)
            n_over = int((per_query[i] >= args.rerank_threshold).sum())
            print(
                f"    query {i + 1}/{len(rerank_queries)}: max={per_query[i].max():.4f}  "
                f"at or above {args.rerank_threshold}: {n_over:,}   {query[:60]}"
            )
        rerank_scores = per_query.max(axis=0)
        rerank_best = per_query.argmax(axis=0)
    print(f"    rerank score distribution:\n{hist(rerank_scores, lo=0.0, hi=1.0)}")

    # --- Assemble candidate table -----------------------------------------------------
    groups = load_media_groups()
    rows = []
    for j, rec in enumerate(cand):
        idx = order[j]
        rows.append(
            {
                "source": rec["source"],
                "media_group": media_group_for(rec["source"], groups),
                "message_id": rec["message_id"],
                "date": rec["date"],
                "is_digest": rec["is_digest"],
                "summary": rec["summary"],
                "original_message": rec["original_message"],
                "views": rec["views"],
                "forwards": rec["forwards"],
                "cosine_max": round(float(max_sim[idx]), 4),
                "cosine_probe": probes[int(best_probe[idx])],
                "rerank_score": round(float(rerank_scores[j]), 4),
                "rerank_probe": rerank_queries[int(rerank_best[j])],
                "keyword_match": bool(keyword_match(rec["summary"], rec["original_message"])),
            }
        )
    df = pd.DataFrame(rows)

    # Drop the sources the study deliberately leaves out (configs/media_groups.yaml,
    # `archived:` — regional outlets and channels that are not news media). Done here,
    # after scoring, because retrieval runs remotely over the whole embedded corpus and
    # cannot filter by source; doing it here keeps the saved dataset in scope.
    archived = load_archived_sources()
    n_archived = int(df["source"].isin(archived).sum())
    if n_archived:
        df = df[~df["source"].isin(archived)].reset_index(drop=True)
        print(f"    dropped {n_archived:,} candidates from archived (out-of-scope) sources")

    base_counts = {
        "embedded_pool": len(records),
        "keyword_full_window": count_keyword_window(match_start, match_end),
        "keyword_embedded_pool": int(keyword_embedded_pool),
        "archived_candidates_dropped": n_archived,
    }
    if args.retriever == "qwen3":
        models = {
            "retriever": "qwen3",
            "embed_model": QWEN_MODEL,
            "embed_input_type": "instruct-query",
            "embed_dim": QWEN_DIM,
            "rerank_model": RERANK_MODEL,
        }
    else:
        models = {
            "retriever": "cohere",
            "embed_model": EMBED_MODEL,
            "embed_input_type": input_type,
            "rerank_model": RERANK_MODEL,
        }
    params = {
        "top_k": args.top_k,
        "cosine_floor": args.cosine_floor,
        "n_probes": len(probes),
        "rerank_mode": args.rerank_mode,
        "n_rerank_queries": len(rerank_queries),
    }
    print("\n[4] Metrics + outputs")
    write_outputs(df, event, win, models, params, base_counts, args)


def rethreshold_from_candidates(args: argparse.Namespace) -> None:
    """Rebuild the dataset at a new --rerank-threshold from a saved candidates.csv. No API calls."""
    cand_path = Path(args.from_candidates)
    df = pd.read_csv(cand_path)
    df = df.drop(columns=[c for c in ("rank", "kept") if c in df.columns])
    if df["keyword_match"].dtype == object:  # robust bool coercion across CSV round-trips
        df["keyword_match"] = (
            df["keyword_match"].astype(str).str.strip().str.lower().isin(("true", "1"))
        )
    else:
        df["keyword_match"] = df["keyword_match"].astype(bool)

    # Candidate files saved before 2026-08-03 still contain the sources that are now
    # archived, so filter here too rather than trusting the file.
    archived = load_archived_sources()
    n_archived = int(df["source"].isin(archived).sum())
    if n_archived:
        df = df[~df["source"].isin(archived)].reset_index(drop=True)
        print(f"    dropped {n_archived:,} candidates from archived (out-of-scope) sources")

    event = load_event(args.year, args.week, args.event)
    win = resolve_window(args)
    models = {
        "embed_model": EMBED_MODEL,
        "embed_input_type": EMBED_INPUT_TYPE,
        "rerank_model": RERANK_MODEL,
    }
    params = {
        "top_k": args.top_k,
        "cosine_floor": args.cosine_floor,
        "n_probes": None,
        "rerank_mode": args.rerank_mode,
        "n_rerank_queries": None,
    }
    base_counts = {
        "embedded_pool": None,
        "keyword_full_window": None,
        "keyword_embedded_pool": int(df["keyword_match"].sum()),
        "archived_candidates_dropped": n_archived,
    }

    # Reuse threshold-independent context from the prior manifest when available.
    man_path = cand_path.with_name(f"event_{args.slug}_manifest.json")
    if man_path.exists():
        prev = json.loads(man_path.read_text(encoding="utf-8"))
        for k in ("embedded_pool", "keyword_full_window", "keyword_embedded_pool"):
            if prev.get("counts", {}).get(k) is not None:
                base_counts[k] = prev["counts"][k]
        for k in ("top_k", "cosine_floor", "n_probes"):
            if prev.get("params", {}).get(k) is not None:
                params[k] = prev["params"][k]
        if prev.get("models"):
            models = prev["models"]

    print(
        f"Re-thresholding {len(df):,} saved candidates "
        f"at rerank>={args.rerank_threshold} (no API) ..."
    )
    write_outputs(df, event, win, models, params, base_counts, args)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--event", default=DEFAULT_EVENT, help="FOM event name (exact match)")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--week", type=int, default=11)
    ap.add_argument(
        "--days-before", type=int, default=None, help="override window days before ISO week"
    )
    ap.add_argument(
        "--days-after", type=int, default=None, help="override window days after ISO week"
    )
    ap.add_argument(
        "--retriever",
        choices=["qwen3", "cohere"],
        default="qwen3",
        help="first-stage embedding retriever (bake-off 2026-07-01: qwen3 matches/mildly "
        "beats cohere; rerank stage is unchanged either way)",
    )
    ap.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="cap on candidates fed to rerank; default is no cap, only --cosine-floor. The "
        "old cap of 3000 was binding: with per-probe reranking 2,235 of 3,000 candidates "
        "cleared the threshold on «Встреча Д. Трампа и В. Зеленского» (measured 2026-08-03), "
        "so the count was reading the cap rather than the coverage.",
    )
    ap.add_argument(
        "--rerank-mode",
        choices=["per-probe", "merged"],
        default="per-probe",
        help="per-probe: one rerank query per probe, keep each post's best score. merged: the "
        "older behaviour, one query made by gluing the event name and all quotes together — "
        "kept only for reproducing earlier builds, see the note at the rerank step.",
    )
    ap.add_argument(
        "--cosine-floor", type=float, default=0.30, help="drop cosine below this before rerank"
    )
    ap.add_argument(
        "--rerank-threshold", type=float, default=0.35, help="keep rerank score >= this"
    )
    ap.add_argument("--slug", default="kursk_2025w11", help="output filename slug")
    ap.add_argument("--out-dir", default=str(DATA_PROCESSED))
    ap.add_argument(
        "--no-space-check", action="store_true", help="skip the embedding-space sanity check"
    )
    ap.add_argument(
        "--space-check-only", action="store_true", help="run only the embedding-space check"
    )
    ap.add_argument(
        "--from-candidates",
        default=None,
        help="rebuild outputs from an existing candidates.csv at --rerank-threshold (no API)",
    )
    args = ap.parse_args()
    if args.from_candidates:
        rethreshold_from_candidates(args)
    else:
        build_dataset(args)


if __name__ == "__main__":
    main()
