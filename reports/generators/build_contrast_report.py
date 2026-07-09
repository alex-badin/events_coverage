#!/usr/bin/env python3
"""Comparison tables from the framing fields the standard readout drops.

Per event, from data/interim/event_<slug>_framing.jsonl:
  1. `causal_attribution` (cause_entity + mechanism): similar cause statements are grouped
     (Qwen3 embedding + KMeans); table = share of each media group's cause statements per group
     of statements.
  2. `emphasized`: similar phrases grouped the same way; table = share of each media group's
     messages that mention the fact.
  3. `moral_evaluation` x `epistemic_status`: mean polarity per actor per group, top roles, and
     the share of ratings that are quoted from someone else rather than said in the outlet's own
     voice.

Output: markdown tables in reports/, CSV matrices + plotly heatmaps in outputs/.
Embeddings are cached in data/interim/framing_embeddings/, so reruns are API-free.

Usage: .venv/bin/python reports/generators/build_contrast_report.py --slug trump_zelensky_2025w10
"""
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "reports" / "generators"))

import cluster_lib  # noqa: E402
from src.events_coverage.matching import QWEN_CLUSTER_INSTRUCTION, embed_texts_qwen3  # noqa: E402

EMB_DIR = ROOT / "data" / "interim" / "framing_embeddings"
OUT_DIR = ROOT / "outputs"
REP_DIR = ROOT / "reports"

SHORT = {
    "Federal TV and state broadcasters": "FedTV",
    "Independent and exile media": "Indep",
    "Mainstream business and general media": "Biz",
    "Pro-government online media": "ProGov",
    "State agencies": "State",
    "War and military channels": "War",
}

# Light merge of frequent surface variants; extraction was not canonicalized for all events.
ALIASES = {
    "zelensky": "Volodymyr Zelenskyy",
    "zelenskyy": "Volodymyr Zelenskyy",
    "volodymyr zelensky": "Volodymyr Zelenskyy",
    "vladimir zelensky": "Volodymyr Zelenskyy",
    "trump": "Donald Trump",
    "donald trump": "Donald Trump",
    "putin": "Vladimir Putin",
    "vladimir putin": "Vladimir Putin",
    "usa": "United States",
    "u.s.": "United States",
    "us": "United States",
    "united states (usa)": "United States",
    "the united states": "United States",
    "vance": "JD Vance",
    "j.d. vance": "JD Vance",
    "jd vance": "JD Vance",
    "ukrainian armed forces (vsu)": "Ukrainian Armed Forces",
    "vsu": "Ukrainian Armed Forces",
    "afu": "Ukrainian Armed Forces",
    "russian armed forces (vs rf)": "Russian Armed Forces",
    "eu": "European Union",
    "europe": "Europe",
}


def canon(entity: str) -> str:
    return ALIASES.get((entity or "").strip().casefold(), (entity or "").strip())


def load_records(slug: str) -> list[dict]:
    path = ROOT / "data" / "interim" / f"event_{slug}_framing.jsonl"
    recs = [json.loads(line) for line in open(path, encoding="utf-8")]
    return [r for r in recs if r.get("on_event", True)]


def embed_cached(slug: str, field: str, texts: list[str]) -> np.ndarray:
    digest = hashlib.sha256("\n".join(texts).encode()).hexdigest()[:16]
    cache = EMB_DIR / f"emb_{slug}_{field}_qwen3_{digest}.npz"
    if cache.exists():
        return np.load(cache)["vecs"].astype(np.float32)
    vecs = embed_texts_qwen3(texts, task=QWEN_CLUSTER_INSTRUCTION)
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(cache, vecs=vecs)
    return vecs


def cluster(vecs: np.ndarray, lo: int, hi: int):
    hi = max(lo, min(hi, len(vecs) - 1))
    return cluster_lib.pick_k_kmeans(vecs, lo=lo, hi=hi)  # (k, silhouette, labels)


def group_share_table(items: list[dict], labels, group_n: dict, message_level: bool) -> pd.DataFrame:
    """Rows = statement/fact groups, cols = media groups. message_level: rate of the media
    group's messages touching the row (for emphasized, where one message yields several
    phrases); otherwise share of the media group's clustered items."""
    per = collections.defaultdict(set) if message_level else collections.defaultdict(int)
    denom = collections.Counter()
    for it, lab in zip(items, labels):
        if message_level:
            per[(lab, it["group"])].add(it["id"])
        else:
            per[(lab, it["group"])] += 1
            denom[it["group"]] += 1
    rows = {}
    groups = sorted(group_n)
    for lab in sorted(set(labels)):
        row = {}
        for g in groups:
            if message_level:
                row[g] = len(per.get((lab, g), set())) / group_n[g]
            else:
                row[g] = per.get((lab, g), 0) / max(denom[g], 1)
        rows[lab] = row
    return pd.DataFrame(rows).T


def matrix_md(share: pd.DataFrame, meta: dict, desc_head: str, desc_len: int = 110) -> list[str]:
    groups = list(share.columns)
    spread = share.max(axis=1) - share.min(axis=1)
    order = spread.sort_values(ascending=False).index
    heads = [desc_head, "n"] + [SHORT.get(g, g) for g in groups] + ["max−min"]
    out = ["| " + " | ".join(heads) + " |", "|" + "|".join([" --- "] * len(heads)) + "|"]
    for lab in order:
        m = meta[lab]
        desc = m["medoid"][:desc_len].replace("|", "/")
        cells = [desc, str(m["size"])] + [f"{share.loc[lab, g]:.0%}" for g in groups]
        cells.append(f"{spread[lab]:.0%}")
        out.append("| " + " | ".join(cells) + " |")
    return out


def heatmap(share: pd.DataFrame, meta: dict, title: str, path: Path) -> None:
    try:
        import plotly.express as px
    except ImportError:
        print("plotly not available; skipped", path.name)
        return
    spread = share.max(axis=1) - share.min(axis=1)
    order = share.loc[spread.sort_values(ascending=False).index]
    labels = [meta[lab]["medoid"][:80] for lab in order.index]
    fig = px.imshow(
        (order.values * 100).round(0).astype(int),
        x=[SHORT.get(g, g) for g in order.columns], y=labels,
        color_continuous_scale="Blues", text_auto=True, aspect="auto",
        title=title, labels=dict(color="% of group"),
    )
    fig.update_layout(height=max(420, 32 * len(labels) + 180),
                      margin=dict(l=10, r=10), yaxis_title=None, xaxis_title=None)
    fig.write_html(path, include_plotlyjs=True)


def df_md(df: pd.DataFrame) -> list[str]:
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "|" + "|".join([" --- "] * len(cols)) + "|"]
    for _, row in df.iterrows():
        out.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return out


def entity_stance(recs: list[dict], min_mentions: int) -> pd.DataFrame:
    rows = []
    for r in recs:
        voice = r.get("epistemic_status") or "?"
        for m in r.get("moral_evaluation") or []:
            ent, role = canon(m.get("entity")), m.get("role")
            pol = m.get("polarity")
            if not ent or role is None or pol is None:
                continue
            rows.append(dict(entity=ent, group=r["media_group"], role=role,
                             polarity=float(np.clip(pol, -2, 2)), voice=voice))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    keep = df.entity.value_counts()
    df = df[df.entity.isin(keep[keep >= min_mentions].index)]
    out = []
    for (ent, g), sub in df.groupby(["entity", "group"]):
        roles = sub.role.value_counts()
        out.append(dict(entity=ent, media_group=g, n=len(sub),
                        mean_polarity=round(sub.polarity.mean(), 2),
                        top_roles=", ".join(f"{r} {c}" for r, c in roles.head(2).items()),
                        share_quoted=round((sub.voice == "attributed").mean(), 2)))
    return pd.DataFrame(out).sort_values(["entity", "media_group"])


def polarity_wide(stance: pd.DataFrame) -> pd.DataFrame:
    """Wide table: rows = entities, one column per media group, cell = 'mean polarity (n)'."""
    wide = {}
    for ent, sub in stance.groupby("entity"):
        row = {}
        for _, r in sub.iterrows():
            row[SHORT.get(r.media_group, r.media_group)] = f"{r.mean_polarity:+.1f} ({r.n})"
        row["total n"] = sub.n.sum()
        wide[ent] = row
    df = pd.DataFrame(wide).T.fillna("—").sort_values("total n", ascending=False)
    return df.reset_index(names="actor")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--min-entity-mentions", type=int, default=12)
    args = ap.parse_args()
    slug = args.slug

    recs = load_records(slug)
    group_n = collections.Counter(r["media_group"] for r in recs)
    group_n = {g: n for g, n in group_n.items() if n >= 15 and not g.startswith("Uncategorized")}
    recs = [r for r in recs if r["media_group"] in group_n]
    print(f"{slug}: {len(recs)} on-event messages, groups: {dict(group_n)}")

    # ---- 1. cause statements ----
    causal_items = []
    for r in recs:
        ca = r.get("causal_attribution") or {}
        ce, me = (ca.get("cause_entity") or "").strip(), (ca.get("mechanism") or "").strip()
        if not (ce or me):
            continue
        text = f"{canon(ce)}: {me}" if ce and me else (canon(ce) or me)
        causal_items.append(dict(text=text, group=r["media_group"], id=r["message_id"]))
    causal_vecs = embed_cached(slug, "causal", [it["text"] for it in causal_items])
    k, sil, labels = cluster(causal_vecs, lo=6, hi=14)
    print(f"cause statements: {len(causal_items)} -> {k} groups (silhouette {sil:.3f})")
    causal_meta = {m["label"]: m for m in
                   cluster_lib.summarize(labels, causal_vecs, [it["text"] for it in causal_items])}
    causal_share = group_share_table(causal_items, labels, group_n, message_level=False)

    # ---- 2. emphasized facts ----
    emph_items = []
    for r in recs:
        for ph in r.get("emphasized") or []:
            ph = (ph or "").strip()
            if ph:
                emph_items.append(dict(text=ph, group=r["media_group"], id=r["message_id"]))
    emph_vecs = embed_cached(slug, "emphasized", [it["text"] for it in emph_items])
    k2, sil2, labels2 = cluster(emph_vecs, lo=10, hi=26)
    print(f"emphasized phrases: {len(emph_items)} -> {k2} groups (silhouette {sil2:.3f})")
    emph_meta = {m["label"]: m for m in
                 cluster_lib.summarize(labels2, emph_vecs, [it["text"] for it in emph_items])}
    emph_share = group_share_table(emph_items, labels2, group_n, message_level=True)

    # ---- 3. actor ratings ----
    stance = entity_stance(recs, args.min_entity_mentions)

    # ---- CSVs ----
    causal_share.to_csv(OUT_DIR / f"event_{slug}_causal_mech_clusters_by_group.csv")
    emph_share.to_csv(OUT_DIR / f"event_{slug}_emphasized_facts_by_group.csv")
    stance.to_csv(OUT_DIR / f"event_{slug}_entity_stance.csv", index=False)
    for name, meta in (("causal_mech_cluster", causal_meta), ("emphasized_fact", emph_meta)):
        pd.DataFrame({lab: dict(medoid=m["medoid"], size=m["size"], terms=" ".join(m["terms"]))
                      for lab, m in meta.items()}).T.to_csv(OUT_DIR / f"event_{slug}_{name}_meta.csv")
    pd.DataFrame(
        [dict(cluster=int(lab), message_id=it["id"], media_group=it["group"], text=it["text"])
         for it, lab in zip(causal_items, labels)]
    ).to_csv(OUT_DIR / f"event_{slug}_causal_mech_assignments.csv", index=False)

    # ---- heatmaps ----
    heatmap(causal_share, causal_meta,
            f"{slug} — cause given for the event (% of group's cause statements)",
            OUT_DIR / f"event_{slug}_causal_heatmap.html")
    heatmap(emph_share, emph_meta,
            f"{slug} — facts highlighted (% of group's messages mentioning it)",
            OUT_DIR / f"event_{slug}_facts_heatmap.html")

    # ---- markdown report (tables only) ----
    legend = ", ".join(f"{SHORT[g]} = {g} ({group_n[g]} msgs)" for g in sorted(group_n))
    md = [f"# Framing comparison tables — {slug}\n",
          f"_{len(recs)} on-event messages. Columns: {legend}._",
          "_Rows are grouped similar statements/phrases; the row text is the most central "
          "example of its group. Shares are within-column. A rating counted as 'quoted' comes "
          "from a message whose core claim is attributed to someone else, so it is framing the "
          "outlet relayed, not necessarily endorsed._\n"]
    md.append(f"## Cause given for the event — % of each group's {len(causal_items)} cause "
              f"statements (field `causal_attribution`)\n")
    md += matrix_md(causal_share, causal_meta, "cause statement (most central example)")
    md.append(f"\n## Facts highlighted — % of each group's messages mentioning it "
              f"(field `emphasized`, {len(emph_items)} phrases)\n")
    md += matrix_md(emph_share, emph_meta, "fact (most central example)")
    md.append("\n## Mean rating of main actors, −2 very negative … +2 very positive "
              "(field `moral_evaluation.polarity`)\n")
    md += df_md(polarity_wide(stance))
    md.append("\n## Actor rating detail: roles and share of ratings quoted from others\n")
    md += df_md(stance)
    (REP_DIR / f"event_{slug}_contrast.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote reports/event_{slug}_contrast.md, 6 CSVs and 2 heatmap HTMLs in outputs/")


if __name__ == "__main__":
    main()
