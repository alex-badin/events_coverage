"""Reusable helpers for building a single-event news dataset.

Two-step matching pipeline:
1. Candidate retrieval by cosine similarity. Two retrievers are supported:
   - "qwen3" (default): qwen/qwen3-embedding-8b vectors (native 4096-d,
     instruction-aware queries). Bake-off (2026-07-01) showed this matches or mildly
     beats the Cohere retriever on the two labeled event windows. The 29GB sidecar
     lives on "Neo" (a LAN box, see [[neo-embedding-box]]) by design — it stays there
     and Neo does the dot-product scoring; only the small query matrix and per-doc
     scores cross the network (see qwen_retrieve_remote()).
   - "cohere": the embedding stored in the DB (embed-multilingual-v3.0,
     input_type=clustering, L2-normalized).
2. Rerank candidates with Cohere rerank-v3.5 to prune false positives (embedder-agnostic,
   unchanged regardless of which retriever was used).

Everything here is read-only against the news database.
"""

from __future__ import annotations

import ast
import csv
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yaml

from .paths import FOM_EVENTS_CLEAN, NEWS_DB, PROJECT_ROOT

CONFIGS_DIR = PROJECT_ROOT / "configs"
MEDIA_GROUPS_YAML = CONFIGS_DIR / "media_groups.yaml"
PROJECT_PATHS_YAML = CONFIGS_DIR / "project_paths.yaml"

# Match the stored document embeddings exactly so the query lands in the same space.
EMBED_MODEL = "embed-multilingual-v3.0"
EMBED_INPUT_TYPE = "clustering"
RERANK_MODEL = "rerank-v3.5"

# Qwen3 sidecar retriever (see scripts/backfill_embeddings_openrouter.py for provenance).
QWEN_MODEL = "qwen/qwen3-embedding-8b"
QWEN_API_URL = "https://openrouter.ai/api/v1/embeddings"
QWEN_PROVIDER = "DeepInfra"
QWEN_DIM = 4096
QWEN_TASK_INSTRUCTION = (
    "Given a news event description, retrieve news messages that report on or discuss "
    "that event."
)
# Clustering is symmetric (no query/document split), so the SAME instruction is applied to
# every framing signature. Focuses the embedding on the framing configuration (roles, action
# naming, blame) rather than the shared event topic — matches the narrative-induction goal.
QWEN_CLUSTER_INSTRUCTION = (
    "Represent this news-framing fingerprint so that messages which frame the event the same "
    "way — the roles assigned to actors, how the action is named, and who is blamed — cluster "
    "together."
)

# The sidecar (and the news_slim.db copy) live on Neo, not on this machine — the dataset
# stays there by design; Neo runs scripts/remote/neo_qwen_retrieve.py to score windows.
NEO_HOST = os.environ.get("NEO_HOST", "${NEO_HOST}")
# Not the older C:\emb_test\venv — Windows Smart App Control (enforced on Neo since
# 2026-07-14) blocks that interpreter outright. numpy_env is a plain `python -m venv`
# whose python.exe is a copy of the signed original, so it runs; numpy's own compiled
# files load there too. See docs/neo_box.md.
NEO_PYTHON = os.environ.get("NEO_PYTHON", r"C:\emb_test\numpy_env\Scripts\python.exe")
NEO_REMOTE_DIR = "C:/emb_test/ec"
NEO_REMOTE_SCRIPT = f"{NEO_REMOTE_DIR}/neo_qwen_retrieve.py"
NEO_SSH_OPTS = ["-o", "ConnectTimeout=20"]

# Keyword anchor for the Kursk / Sudzha event. Used ONLY to estimate recall/precision
# against a transparent baseline, never as the final filter. Stems catch inflections:
# "курск" -> Курск/Курская/Курской/Курске; "судж" -> Суджа/Суджи/Суджу/Суджанский.
KEYWORD_PATTERN = re.compile(r"курск|судж", re.IGNORECASE)

# Label for a source that is in neither the groups nor the archived list. Every source in
# the news database is accounted for in configs/media_groups.yaml as of 2026-08-03, so this
# should never appear. It exists so that an unknown source is loud rather than dropped —
# the dbt `accepted_values` test on media_group rejects it and the build fails.
UNKNOWN_GROUP_LABEL = "Ungrouped source (unexpected)"


# --------------------------------------------------------------------------- config
def load_defaults() -> dict:
    """Return the `defaults:` block from configs/project_paths.yaml."""
    with open(PROJECT_PATHS_YAML, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("defaults", {}) or {}


def load_media_groups(path=MEDIA_GROUPS_YAML) -> dict[str, str]:
    """Map source -> human-readable media-group label, for in-scope sources only.

    Archived sources are not in the returned map; use `load_archived_sources` for those.
    """
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    mapping: dict[str, str] = {}
    for key, grp in (cfg.get("groups") or {}).items():
        label = (grp or {}).get("label", key)
        for source in (grp or {}).get("sources", []) or []:
            mapping[source] = label
    return mapping


def load_archived_sources(path=MEDIA_GROUPS_YAML) -> set[str]:
    """Sources deliberately left out of the study (decided 2026-08-03).

    Read from the `archived:` block of configs/media_groups.yaml, which groups them by
    reason (`reason_regional`, `reason_not_media`). Every reason list is pooled here,
    because every caller wants the same thing: the set of sources to drop.
    """
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    archived: set[str] = set()
    for sources in (cfg.get("archived") or {}).values():
        archived.update(sources or [])
    return archived


def media_group_for(source: str, mapping: dict[str, str]) -> str:
    return mapping.get(source, UNKNOWN_GROUP_LABEL)


# ----------------------------------------------------------------------------- event
def iso_week_window(year: int, week: int, days_before: int, days_after: int):
    """ISO week -> (match_start, match_end_exclusive, week_monday, week_sunday) as dates."""
    monday = date.fromisocalendar(year, week, 1)
    sunday = date.fromisocalendar(year, week, 7)
    match_start = monday - timedelta(days=days_before)
    match_end = sunday + timedelta(days=days_after) + timedelta(days=1)  # half-open upper bound
    return match_start, match_end, monday, sunday


def parse_quotes(raw: str | None) -> list[str]:
    """Parse the FOM `description` cell (a Python-list literal of quotes) into a list."""
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return []
    try:
        value = ast.literal_eval(raw)
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
    except (ValueError, SyntaxError):
        pass
    return [raw]


def load_event(year: int, week: int, name: str | None = None, path=FOM_EVENTS_CLEAN) -> dict:
    """Load one FOM event (name + quotes + percentage) from the cleaned events table."""
    matches = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                if int(row["year"]) == year and int(row["week"]) == week:
                    matches.append(row)
            except (ValueError, KeyError):
                continue
    if not matches:
        raise ValueError(f"No FOM events found for year={year} week={week} in {path}")
    if name:
        named = [r for r in matches if r["event"].strip() == name.strip()]
        if not named:
            available = "\n  - ".join(sorted(r["event"] for r in matches))
            raise ValueError(
                f"Event {name!r} not found for {year} week {week}. Available:\n  - {available}"
            )
        row = named[0]
    else:
        row = matches[0]
    return {
        "name": row["event"].strip(),
        "quotes": parse_quotes(row.get("description")),
        "percentage": row.get("percentage"),
        "year": year,
        "week": week,
    }


def build_probes(event: dict) -> list[str]:
    """Query probe texts: the event name, each quote, and one combined string.

    Multiple short probes + max-pooling favors recall for the short colloquial quotes.
    """
    name = event["name"]
    quotes = [q.strip('«»" ') for q in event["quotes"]]
    combined = ". ".join([name, *quotes])
    probes = [name, *quotes, combined]
    # de-duplicate while preserving order
    seen, out = set(), []
    for p in probes:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


# ----------------------------------------------------------------------- news loading
def _fmt(d: date) -> str:
    return d.isoformat()


def load_window_messages(start: date, end: date, db_path=NEWS_DB, require_embedding: bool = True):
    """Load messages in [start, end) (half-open). Returns (records, embedding_matrix_or_None).

    Lexicographic comparison works because `date` is stored as ISO 8601 text and the
    bounds are date-only prefixes.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql = (
        "SELECT source, message_id, date, is_digest, summary, original_message, "
        "views, forwards, embedding FROM unified_messages "
        "WHERE date >= ? AND date < ?"
    )
    if require_embedding:
        # Some rows have a non-NULL but empty/garbage embedding (e.g. ''); '[%' keeps
        # only JSON-array strings so records and the matrix stay aligned.
        sql += " AND embedding LIKE '[%'"
    sql += " ORDER BY date"

    records: list[dict] = []
    vectors: list[np.ndarray] = []
    skipped = 0
    for row in con.execute(sql, (_fmt(start), _fmt(end))):
        rec = {
            "source": row["source"],
            "message_id": row["message_id"],
            "date": row["date"],
            "is_digest": row["is_digest"],
            "summary": row["summary"],
            "original_message": row["original_message"],
            "views": row["views"],
            "forwards": row["forwards"],
        }
        if not require_embedding:
            records.append(rec)
            continue
        try:  # parse defensively: skip BOTH record and vector on any bad embedding
            vec = np.asarray(json.loads(row["embedding"]), dtype=np.float32)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if vec.ndim != 1 or vec.size == 0:
            skipped += 1
            continue
        vectors.append(vec)
        records.append(rec)
    con.close()
    if skipped:
        print(f"    (skipped {skipped} rows with unparseable embeddings)")

    matrix = l2_normalize(np.vstack(vectors)) if (require_embedding and vectors) else None
    return records, matrix


def count_keyword_window(start: date, end: date, db_path=NEWS_DB) -> int:
    """Count window messages hitting the keyword anchor (incl. rows without embeddings).

    Done in Python on purpose: SQLite's lower()/LIKE are ASCII-only and silently miss
    capitalized Cyrillic (e.g. «Курск»), so an in-SQL count badly undercounts.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.execute(
        "SELECT summary, original_message FROM unified_messages WHERE date >= ? AND date < ?",
        (_fmt(start), _fmt(end)),
    )
    n = sum(1 for summary, original in cur if keyword_match(summary, original))
    con.close()
    return n


def sample_keyword_embedded(start: date, end: date, limit: int = 5, db_path=NEWS_DB):
    """Return (records, stored_matrix) for a few embedded, keyword-matching messages.

    Used by the embedding-space sanity check (re-embed summary, compare to stored vector).
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql = (
        "SELECT source, message_id, summary, embedding FROM unified_messages "
        "WHERE date >= ? AND date < ? AND embedding LIKE '[%' AND summary IS NOT NULL "
        "AND lower(summary) LIKE ? ORDER BY date LIMIT ?"
    )
    rows = con.execute(sql, (_fmt(start), _fmt(end), "%судж%", limit)).fetchall()
    con.close()
    records = [
        {"source": r["source"], "message_id": r["message_id"], "summary": r["summary"]}
        for r in rows
    ]
    stored = (
        np.vstack([np.asarray(json.loads(r["embedding"]), dtype=np.float32) for r in rows])
        if rows
        else None
    )
    return records, (l2_normalize(stored) if stored is not None else None)


def load_messages_by_keys(keys, db_path=NEWS_DB, chunk_size=500) -> dict:
    """Fetch full records (summary, original_message, etc.) for exact (source, message_id)
    keys, e.g. to enrich a qwen3-selected candidate list with text for reranking/output.
    keys: iterable of (source, message_id) with message_id as str or int.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    by_source: dict[str, list] = {}
    for src, mid in keys:
        by_source.setdefault(src, []).append(int(mid))
    records: dict[tuple[str, str], dict] = {}
    sql_cols = "source, message_id, date, is_digest, summary, original_message, views, forwards"
    for src, mids in by_source.items():
        for i in range(0, len(mids), chunk_size):
            chunk = mids[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            sql = (
                f"SELECT {sql_cols} FROM unified_messages "
                f"WHERE source = ? AND message_id IN ({placeholders})"
            )
            for row in con.execute(sql, (src, *chunk)):
                records[(row["source"], str(row["message_id"]))] = dict(row)
    con.close()
    return records


def qwen_retrieve_remote(
    start: date,
    end: date,
    query_matrix: np.ndarray,
    host: str = NEO_HOST,
    top_k=None,
    floor=None,
):
    """Score the Qwen3 sidecar window [start, end) against query_matrix — ON NEO.

    The sidecar (29GB) and the news_slim.db copy live on Neo by design (see
    [[neo-embedding-box]]); this never pulls the doc vectors here. Only the small
    query_matrix (query_matrix.npy, tens of KB) goes out and a small per-doc score
    tsv comes back. Runs scripts/remote/neo_qwen_retrieve.py over SSH.

    Returns (order, max_sim, best_probe, records) — same shape contract as
    cosine_topk() plus records (source, message_id, date; no text — see
    load_messages_by_keys() for that).
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        q_local = tmp / "query.npy"
        out_local = tmp / "scores.tsv"
        np.save(q_local, np.asarray(query_matrix, dtype=np.float32))

        q_remote = f"{NEO_REMOTE_DIR}/_query_{os.getpid()}.npy"
        out_remote = f"{NEO_REMOTE_DIR}/_scores_{os.getpid()}.tsv"
        try:
            subprocess.run(
                ["scp", *NEO_SSH_OPTS, str(q_local), f"{host}:{q_remote}"],
                check=True, capture_output=True, text=True,
            )
            cmd = f'{NEO_PYTHON} {NEO_REMOTE_SCRIPT.replace("/", chr(92))} ' \
                  f'{_fmt(start)} {_fmt(end)} "{q_remote}" "{out_remote}"'
            subprocess.run(
                ["ssh", *NEO_SSH_OPTS, host, cmd], check=True, capture_output=True, text=True
            )
            subprocess.run(
                ["scp", *NEO_SSH_OPTS, f"{host}:{out_remote}", str(out_local)],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"qwen3 remote retrieval on Neo failed: {e.stderr or e.stdout}"
            ) from e
        finally:
            subprocess.run(
                ["ssh", *NEO_SSH_OPTS, host, f"del /q {q_remote.replace('/', chr(92))} "
                 f"{out_remote.replace('/', chr(92))} 2>nul"],
                capture_output=True,
            )

        records, sims, probes = [], [], []
        with open(out_local, encoding="utf-8") as f:
            for line in f:
                mid, src, dt, sim, bp = line.rstrip("\n").split("\t")
                records.append({"source": src, "message_id": mid, "date": dt})
                sims.append(float(sim))
                probes.append(int(bp))

    max_sim = np.asarray(sims, dtype=np.float32)
    best_probe = np.asarray(probes, dtype=np.int64)
    order = rank_and_trim(max_sim, top_k=top_k, floor=floor)
    return order, max_sim, best_probe, records


# ------------------------------------------------------------------------- vector ops
def l2_normalize(mat: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    mat = np.asarray(mat, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.maximum(norms, eps)


def rank_and_trim(max_sim: np.ndarray, top_k=None, floor=None) -> np.ndarray:
    """Descending-score order, optionally floored then capped at top_k."""
    order = np.argsort(-max_sim)
    if floor is not None:
        order = order[max_sim[order] >= floor]
    if top_k is not None:
        order = order[:top_k]
    return order


def cosine_topk(doc_matrix: np.ndarray, query_matrix: np.ndarray, top_k=None, floor=None):
    """Per-doc max cosine over query probes. Returns (order, max_sim, best_probe_idx).

    Both inputs must be L2-normalized; cosine then reduces to a dot product.
    """
    sims = doc_matrix @ query_matrix.T  # (N_docs, N_probes)
    max_sim = sims.max(axis=1)
    best_probe = sims.argmax(axis=1)
    order = rank_and_trim(max_sim, top_k=top_k, floor=floor)
    return order, max_sim, best_probe


# ------------------------------------------------------------------------------ cohere
def _is_rate_limit(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if "toomanyrequests" in name or "ratelimit" in name:
        return True
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return code == 429


def _call_with_retry(fn, what="cohere call", max_retries=6, base=2.0, cap=60.0):
    """Call fn(); on a Cohere rate-limit (429) back off and retry, otherwise re-raise."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - only swallowed when it's a rate limit
            if _is_rate_limit(exc) and attempt < max_retries:
                wait = min(cap, base**attempt)
                print(
                    f"    rate limited on {what}; retry {attempt + 1}/{max_retries} "
                    f"in {wait:.0f}s ..."
                )
                time.sleep(wait)
                continue
            raise


def get_cohere_client(api_key: str | None = None):
    """Build a Cohere ClientV2, loading COHERE_API_KEY from .env if needed."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    key = api_key or os.environ.get("COHERE_API_KEY")
    if not key:
        raise RuntimeError(
            "COHERE_API_KEY is not set. Copy .env.example to .env and add your key "
            "(needed for both the query embedding and the rerank step)."
        )
    import cohere

    return cohere.ClientV2(api_key=key)


def embed_texts(client, texts, input_type=EMBED_INPUT_TYPE, model=EMBED_MODEL, batch_size=96):
    """Embed texts with Cohere and return an L2-normalized float32 matrix."""
    texts = list(texts)
    out: list = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        resp = _call_with_retry(
            lambda chunk=chunk: client.embed(
                model=model, texts=chunk, input_type=input_type, embedding_types=["float"]
            ),
            what=f"embed ({input_type})",
        )
        emb = resp.embeddings
        floats = getattr(emb, "float_", None) or getattr(emb, "float", None)
        if floats is None and isinstance(emb, list):
            floats = emb
        out.extend(floats)
    return l2_normalize(np.asarray(out, dtype=np.float32))


def rerank(client, query, documents, model=RERANK_MODEL, batch_size=1000, max_tokens_per_doc=2048):
    """Rerank documents (list of strings) against query. Returns float32 scores aligned to input."""
    documents = list(documents)
    scores = np.zeros(len(documents), dtype=np.float32)
    for i in range(0, len(documents), batch_size):
        chunk = documents[i : i + batch_size]
        resp = _call_with_retry(
            lambda chunk=chunk: client.rerank(
                model=model,
                query=query,
                documents=chunk,
                top_n=len(chunk),
                max_tokens_per_doc=max_tokens_per_doc,
            ),
            what=f"rerank (batch {i // batch_size + 1})",
        )
        for result in resp.results:
            scores[i + result.index] = result.relevance_score
    return scores


# --------------------------------------------------------------------------- openrouter
def get_openrouter_key(api_key: str | None = None) -> str:
    """Load OPENROUTER_API_KEY from .env if needed."""
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key "
            "(needed to embed query probes for the qwen3 retriever)."
        )
    return key


def _qwen_embed_batch(texts, key, dim, provider, max_retries=6):
    body = {"model": QWEN_MODEL, "input": list(texts)}
    if dim:
        body["dimensions"] = dim
    if provider:
        body["provider"] = {"order": [provider], "allow_fallbacks": False}
    payload = json.dumps(body).encode()
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(QWEN_API_URL, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Title", "events-coverage-matcher")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read())
            data = sorted(resp["data"], key=lambda d: d["index"])
            return np.asarray([d["embedding"] for d in data], dtype=np.float32)
        except urllib.error.HTTPError as e:
            transient = e.code in (429, 500, 502, 503, 504)
            if transient and attempt < max_retries:
                wait = min(60.0, 2.0**attempt)
                print(f"    {e.code} on qwen3 embed batch; retry {attempt + 1} in {wait:.0f}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < max_retries:
                wait = min(60.0, 2.0**attempt)
                print(f"    network error ({e}); retry {attempt + 1} in {wait:.0f}s")
                time.sleep(wait)
                continue
            raise


def embed_texts_qwen3(
    texts,
    task: str = QWEN_TASK_INSTRUCTION,
    dim: int = QWEN_DIM,
    provider: str = QWEN_PROVIDER,
    api_key: str | None = None,
    batch_size: int = 64,
):
    """Embed texts with qwen3 via OpenRouter. Two uses:

    - **Retrieval queries** (event probes, default `task`): the instruction goes only on the
      query; sidecar documents were embedded plain. Confirmed by the bake-off — omitting the
      ``Instruct: {task}\\nQuery: {text}`` prefix made qwen3 look ~5-8pts worse before the fix.
    - **Clustering** (pass ``task=QWEN_CLUSTER_INSTRUCTION``): the same instruction is applied to
      every text, so the set sits in one symmetric space (used by narrative induction).
    - Pass ``task=None`` to embed plain (reproduces the sidecar document space).

    Returns an L2-normalized float32 matrix; truncating `dim` below the native 4096 reproduces
    the server-side MRL truncation exactly (verified 2026-06-29), so it stays comparable to a
    sidecar built at the same or a smaller dim.
    """
    key = get_openrouter_key(api_key)
    texts = list(texts)
    # task=None -> embed plain (matches how the sidecar documents were embedded); otherwise
    # apply the instruction to every text (a query for retrieval, or all signatures for clustering).
    prefixed = [f"Instruct: {task}\nQuery: {t}" for t in texts] if task else list(texts)
    out: list = []
    for i in range(0, len(prefixed), batch_size):
        chunk = prefixed[i : i + batch_size]
        out.extend(_qwen_embed_batch(chunk, key, dim, provider))
    return l2_normalize(np.asarray(out, dtype=np.float32))


# ------------------------------------------------------------------------------- misc
def keyword_match(*texts: str | None) -> bool:
    """True if any provided text hits the Kursk/Sudzha keyword anchor."""
    return any(t and KEYWORD_PATTERN.search(t) for t in texts)
