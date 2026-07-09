#!/usr/bin/env python3
"""Stage 2: induce per-event narratives from the framing records, then reclassify all messages.

A "narrative" here is a recurring CONFIGURATION of framing (problem definition + action labels +
causal attribution + entity roles), NOT a topic. We cluster on the framing SIGNATURE (never the raw
text, which would collapse because the matched messages are already similar), have gpt-5.5 consolidate
the clusters into <=8 named narratives, then reclassify every message into that fixed taxonomy so the
labels are stable and comparable across media groups.

Input : data/interim/event_<slug>_framing.jsonl   (from extract_framing.py)
Output: data/interim/event_<slug>_narratives.jsonl + event_<slug>_taxonomy.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from pydantic import BaseModel
from sklearn.cluster import HDBSCAN, KMeans

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.events_coverage import framing as F
from src.events_coverage.matching import QWEN_CLUSTER_INSTRUCTION, embed_texts_qwen3
from src.events_coverage.paths import DATA_INTERIM


def signature(rec: dict) -> str:
    """Compact framing fingerprint used for clustering and reclassification."""
    parts = []
    if rec.get("problem_definition"):
        parts.append(rec["problem_definition"])
    terms = [a.get("term") for a in rec.get("action_labels") or [] if a.get("term")]
    if terms:
        parts.append("labels: " + ", ".join(terms))
    ca = rec.get("causal_attribution") or {}
    if ca.get("cause_entity"):
        parts.append("cause: " + str(ca["cause_entity"]))
    roles = [f"{m.get('entity')}={m.get('role')}" for m in rec.get("moral_evaluation") or []
             if m.get("entity")]
    if roles:
        parts.append("roles: " + "; ".join(roles))
    if rec.get("epistemic_status"):
        parts.append("epistemic: " + str(rec["epistemic_status"]))
    return " | ".join(parts) or (rec.get("problem_definition") or "n/a")


class Narrative(BaseModel):
    id: str
    name: str
    description: str


class Taxonomy(BaseModel):
    narratives: list[Narrative]


class Assignment(BaseModel):
    index: int
    narrative_id: str


class Assignments(BaseModel):
    items: list[Assignment]


def cluster_exemplars(sigs, emb, labels, per_cluster=6):
    """Return {cluster_label: (size, [exemplar signatures near centroid])}, excluding noise (-1)."""
    out = {}
    for lab in sorted(set(labels)):
        if lab == -1:
            continue
        idx = np.where(labels == lab)[0]
        centroid = emb[idx].mean(axis=0)
        order = idx[np.argsort(-(emb[idx] @ centroid))]
        out[int(lab)] = (len(idx), [sigs[i] for i in order[:per_cluster]])
    return out


def propose_taxonomy(client, exemplars, n_noise, max_narratives, model):
    blocks = []
    for lab, (size, exs) in sorted(exemplars.items(), key=lambda kv: -kv[1][0]):
        ex_lines = "\n".join(f"     · {e}" for e in exs)
        blocks.append(f"  Cluster {lab} (n={size}):\n{ex_lines}")
    listing = "\n".join(blocks)
    sys_p = (
        "You consolidate clusters of news-framing fingerprints into a small set of distinct "
        "NARRATIVES — recurring ways outlets frame ONE event (who is cast as what, how the action "
        "is named, who is blamed). Merge near-duplicates; keep genuinely opposed framings separate "
        f"(e.g. liberation vs occupation). Produce at most {max_narratives} narratives, each with a "
        "short snake_case id, a human name, and a one-line description. Add an 'other_mixed' "
        "narrative only if needed for leftovers.")
    usr_p = f"Framing clusters ({n_noise} unclustered/noise points not shown):\n{listing}"
    obj, _ = F.structured_parse(client, sys_p, usr_p, Taxonomy, model, max_output_tokens=5000)
    return obj


def reclassify(client, sigs, taxonomy: Taxonomy, model, batch_size=30):
    ids = [n.id for n in taxonomy.narratives]
    tax_desc = "\n".join(f"  - {n.id}: {n.name} — {n.description}" for n in taxonomy.narratives)
    sys_p = ("Assign each framing fingerprint to exactly one narrative id from the taxonomy. "
             "Use the id that best matches the framing (roles, labels, blame). "
             f"If none fit, use 'other_mixed' if present else '{ids[0]}'.\nTaxonomy:\n" + tax_desc)
    assigned = ["" for _ in sigs]
    for start in range(0, len(sigs), batch_size):
        chunk = sigs[start:start + batch_size]
        listing = "\n".join(f"[{start + i}] {s}" for i, s in enumerate(chunk))
        usr_p = f"Fingerprints:\n{listing}"
        obj, _ = F.structured_parse(client, sys_p, usr_p, Assignments, model, max_output_tokens=6000)
        items = obj.items
        for it in items:
            if 0 <= it.index < len(sigs):
                assigned[it.index] = it.narrative_id if it.narrative_id in ids else (
                    "other_mixed" if "other_mixed" in ids else ids[0])
        print(f"  reclassified {min(start + batch_size, len(sigs))}/{len(sigs)}")
    # fill any blanks
    fallback = "other_mixed" if "other_mixed" in ids else ids[0]
    return [a or fallback for a in assigned]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", default="kursk_2025w11")
    ap.add_argument("--input", type=Path, default=None)
    ap.add_argument("--max-narratives", type=int, default=8)
    ap.add_argument("--min-cluster-size", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=30)
    ap.add_argument("--include-off-event", action="store_true",
                    help="also induce over messages flagged on_event=false")
    args = ap.parse_args()

    in_path = args.input or (DATA_INTERIM / f"event_{args.slug}_framing.jsonl")
    records = [json.loads(line) for line in open(in_path, encoding="utf-8")]
    kept = records if args.include_off_event else [r for r in records if r.get("on_event", True)]
    print(f"{len(records)} records | {len(kept)} on-event used for induction")

    sigs = [signature(r) for r in kept]
    print("embedding signatures (Qwen3 clustering space) ...")
    emb = embed_texts_qwen3(sigs, task=QWEN_CLUSTER_INSTRUCTION)  # L2-normalized, 4096-d

    mcs = args.min_cluster_size or max(5, len(sigs) // 40)
    labels = HDBSCAN(min_cluster_size=mcs, min_samples=1, metric="euclidean").fit_predict(emb)
    n_clusters = len(set(labels) - {-1})
    n_noise = int((labels == -1).sum())
    print(f"HDBSCAN: {n_clusters} clusters, {n_noise} noise (min_cluster_size={mcs})")

    # One event's signatures sit in a tight, high-cosine space (qwen3 mean off-diagonal ~0.70),
    # so HDBSCAN tends to UNDER-SEED: too few clusters, one dominant blob, or most points as noise.
    # Any of those starve the LLM of diverse exemplars — and push minority/opposed framings into
    # excluded noise, which is exactly the divergence signal we care about. When that happens, seed
    # with KMeans instead: it partitions everything into k balanced groups purely for exemplar
    # diversity; the LLM does the real consolidation.
    clustered = labels[labels != -1]
    dominant = (np.bincount(clustered).max() / clustered.size) if clustered.size else 1.0
    noise_frac = n_noise / max(1, len(sigs))
    if n_clusters < 3 or dominant > 0.6 or noise_frac > 0.5:
        k = min(args.max_narratives, max(3, len(sigs) // 40))
        print(f"  -> under-seeded (clusters={n_clusters}, dominant={dominant:.0%}, "
              f"noise={noise_frac:.0%}); falling back to KMeans(k={k}) for exemplar seeding")
        labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(emb)
        n_clusters, n_noise = k, 0

    openai = F.get_openai_client()
    exemplars = cluster_exemplars(sigs, emb, labels)
    taxonomy = propose_taxonomy(openai, exemplars, n_noise, args.max_narratives, F.MODEL)
    if not taxonomy.narratives:
        taxonomy = Taxonomy(narratives=[Narrative(
            id="general_coverage", name="General coverage",
            description="Fallback narrative; taxonomy induction returned none.")])
    print(f"\nproposed {len(taxonomy.narratives)} narratives:")
    for n in taxonomy.narratives:
        print(f"  - {n.id}: {n.name} — {n.description}")

    print("\nreclassifying all on-event messages into the taxonomy ...")
    assigned = reclassify(openai, sigs, taxonomy, F.MODEL, args.batch_size)
    name_by_id = {n.id: n.name for n in taxonomy.narratives}

    out_path = DATA_INTERIM / f"event_{args.slug}_narratives.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for rec, sig, nid in zip(kept, sigs, assigned):
            rec = {**rec, "signature": sig, "narrative_id": nid,
                   "narrative_name": name_by_id.get(nid, nid)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tax_path = DATA_INTERIM / f"event_{args.slug}_taxonomy.json"
    tax_path.write_text(taxonomy.model_dump_json(indent=2), encoding="utf-8")

    from collections import Counter
    dist = Counter(assigned)
    print("\nnarrative sizes:")
    for nid, c in dist.most_common():
        print(f"  {c:4d}  {nid} — {name_by_id.get(nid, nid)}")
    print(f"\n-> {out_path}\n-> {tax_path}")


if __name__ == "__main__":
    main()
