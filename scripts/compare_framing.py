#!/usr/bin/env python3
"""Stage 3: compare framing across media groups for one event.

Everything is normalized WITHIN media group (never raw counts, because group sizes are very
uneven), and every narrative share carries a bootstrap 95% CI so small groups are not over-read.

Input : data/interim/event_<slug>_narratives.jsonl
Output: outputs/event_<slug>_*.csv  +  outputs/event_<slug>_narrative_heatmap.html
        reports/event_<slug>_framing.md   (deterministic, rendered straight from the tables)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.events_coverage.paths import DATA_INTERIM, OUTPUTS, REPORTS

def df_to_md(df: pd.DataFrame) -> str:
    """Render a DataFrame (with index) as a markdown table, without the tabulate dependency."""
    cols = [str(df.index.name or "")] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |",
             "| " + " | ".join(["---"] * len(cols)) + " |"]
    for idx, row in df.iterrows():
        lines.append("| " + " | ".join([str(idx)] + [f"{v}" for v in row.tolist()]) + " |")
    return "\n".join(lines)


MIN_N = 30  # below this, a group's shares are "directional only"
# A "contradiction" = the same entity cast in a sympathetic role by one group and a
# condemnatory role by another (the role's valence sign flips across groups).
POSITIVE_ROLES = {"liberator", "defender", "hero", "victim", "protector", "ally",
                  "beneficiary", "mediator"}
NEGATIVE_ROLES = {"aggressor", "occupier", "perpetrator", "villain", "provocateur",
                  "threat", "traitor"}
SEMETKO = ["conflict", "human_interest", "economic_consequences", "morality", "responsibility"]


def _role_valence(role: str) -> str:
    if role in POSITIVE_ROLES:
        return "pos"
    if role in NEGATIVE_ROLES:
        return "neg"
    return "neu"


def load(slug, in_path):
    in_path = in_path or (DATA_INTERIM / f"event_{slug}_narratives.jsonl")
    recs = [json.loads(line) for line in open(in_path, encoding="utf-8")]
    recs = [r for r in recs if r.get("on_event", True)]
    return recs


def bootstrap_share_ci(labels: list[str], categories: list[str], b=1000, seed=0):
    """Return {category: (share, lo, hi)} for one group's label list via bootstrap."""
    rng = np.random.default_rng(seed)
    n = len(labels)
    idx = {c: i for i, c in enumerate(categories)}
    arr = np.array([idx[x] for x in labels if x in idx])
    if n == 0:
        return {c: (0.0, 0.0, 0.0) for c in categories}
    base = np.bincount(arr, minlength=len(categories)) / n
    boot = np.empty((b, len(categories)))
    for i in range(b):
        s = rng.integers(0, n, n)
        boot[i] = np.bincount(arr[s], minlength=len(categories)) / n
    lo, hi = np.percentile(boot, [2.5, 97.5], axis=0)
    return {c: (float(base[idx[c]]), float(lo[idx[c]]), float(hi[idx[c]])) for c in categories}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", default="kursk_2025w11")
    ap.add_argument("--input", type=Path, default=None)
    ap.add_argument("--bootstrap", type=int, default=1000)
    args = ap.parse_args()
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    recs = load(args.slug, args.input)
    df = pd.DataFrame(recs)
    groups = sorted(df["media_group"].dropna().unique())
    group_n = df["media_group"].value_counts().to_dict()
    narratives = sorted(df["narrative_id"].dropna().unique())
    nname = {r["narrative_id"]: r.get("narrative_name", r["narrative_id"]) for r in recs}
    out = lambda name: OUTPUTS / f"event_{args.slug}_{name}"

    # ---- 1. narrative x group share + bootstrap CIs ----
    share = pd.DataFrame(index=narratives, columns=groups, dtype=float)
    ci_rows = []
    for g in groups:
        labels = df.loc[df.media_group == g, "narrative_id"].tolist()
        ci = bootstrap_share_ci(labels, narratives, b=args.bootstrap)
        for nid in narratives:
            s, lo, hi = ci[nid]
            share.loc[nid, g] = s
            ci_rows.append({"media_group": g, "n": group_n[g], "narrative_id": nid,
                            "narrative": nname.get(nid, nid), "share": round(s, 3),
                            "ci_lo": round(lo, 3), "ci_hi": round(hi, 3),
                            "directional_only": group_n[g] < MIN_N})
    share.to_csv(out("narrative_by_group_share.csv"))
    pd.DataFrame(ci_rows).to_csv(out("narrative_by_group_ci.csv"), index=False)

    # ---- 2. pairwise JS divergence between groups' narrative distributions ----
    js = pd.DataFrame(index=groups, columns=groups, dtype=float)
    for g in groups:
        js.loc[g, g] = 0.0
    for a, b in combinations(groups, 2):
        d = float(jensenshannon(share[a].values + 1e-12, share[b].values + 1e-12, base=2))
        js.loc[a, b] = js.loc[b, a] = round(d, 3)
    js.to_csv(out("group_js_divergence.csv"))

    # ---- 3. entity-role contingency + role-flip detection ----
    role_counts = defaultdict(Counter)          # (group, entity) -> role counts
    ent_group_support = defaultdict(Counter)     # entity -> group counts
    for r in recs:
        g = r.get("media_group")
        for m in r.get("moral_evaluation") or []:
            ent, role = m.get("entity"), m.get("role")
            if ent and role:
                role_counts[(g, ent)][role] += 1
                ent_group_support[ent][g] += 1
    cont_rows = []
    for (g, ent), rc in role_counts.items():
        tot = sum(rc.values())
        for role, c in rc.items():
            cont_rows.append({"media_group": g, "entity": ent, "role": role, "count": c,
                              "share_in_group_entity": round(c / tot, 3)})
    pd.DataFrame(cont_rows).sort_values(["entity", "media_group", "count"],
                                        ascending=[True, True, False]).to_csv(
        out("entity_role_contingency.csv"), index=False)

    flip_rows = []
    for ent, gsupport in ent_group_support.items():
        groups_with = [g for g, c in gsupport.items() if c >= 3]
        if len(groups_with) < 2:
            continue
        dom = {g: role_counts[(g, ent)].most_common(1)[0][0] for g in groups_with}
        distinct = set(dom.values())
        if len(distinct) < 2:
            continue
        valences = {_role_valence(r) for r in distinct}
        opposed = "pos" in valences and "neg" in valences
        flip_rows.append({"entity": ent, "n_groups": len(groups_with),
                          "opposed_contradiction": opposed,
                          **{g: f"{dom[g]} ({gsupport[g]})" for g in groups_with}})
    flips = pd.DataFrame(flip_rows).sort_values("opposed_contradiction", ascending=False) \
        if flip_rows else pd.DataFrame()
    flips.to_csv(out("role_flips.csv"), index=False)

    # ---- 4. action-label lexicon by group ----
    lex = defaultdict(Counter)
    for r in recs:
        g = r.get("media_group")
        for a in r.get("action_labels") or []:
            if a.get("term"):
                lex[g][(a["term"], a.get("valence", ""))] += 1
    lex_rows = [{"media_group": g, "term": t, "valence": v, "count": c}
                for g, cnt in lex.items() for (t, v), c in cnt.most_common(15)]
    pd.DataFrame(lex_rows).to_csv(out("action_label_lexicon.csv"), index=False)

    # ---- 5. epistemic status by group (share) ----
    epi = pd.crosstab(df.media_group, df.epistemic_status, normalize="index").round(3)
    epi.to_csv(out("epistemic_by_group.csv"))

    # ---- 6. causal attribution (top cause entity) by group ----
    cause = defaultdict(Counter)
    for r in recs:
        ce = (r.get("causal_attribution") or {}).get("cause_entity")
        if ce:
            cause[r.get("media_group")][ce] += 1
    cause_rows = [{"media_group": g, "cause_entity": ce, "count": c,
                   "share": round(c / group_n[g], 3)}
                  for g, cnt in cause.items() for ce, c in cnt.most_common(6)]
    pd.DataFrame(cause_rows).to_csv(out("causal_by_group.csv"), index=False)

    # ---- 7. Semetko frame prevalence by group ----
    sem = pd.DataFrame(index=groups, columns=SEMETKO, dtype=float)
    for g in groups:
        sub = df[df.media_group == g]
        for fr in SEMETKO:
            sem.loc[g, fr] = round(sub["semetko"].apply(lambda s: bool(s.get(fr))).mean(), 3)
    sem.to_csv(out("semetko_by_group.csv"))

    # ---- 8. entity omission: union of well-covered entities vs each group ----
    ent_total = Counter()
    ent_by_group = defaultdict(Counter)
    for r in recs:
        g = r.get("media_group")
        seen = {e.get("canonical") for e in r.get("entities") or [] if e.get("canonical")}
        for e in seen:
            ent_total[e] += 1
            ent_by_group[g][e] += 1
    top_entities = [e for e, _ in ent_total.most_common(20)]
    omit = pd.DataFrame(index=top_entities, columns=groups, dtype=float)
    for g in groups:
        for e in top_entities:
            omit.loc[e, g] = round(ent_by_group[g][e] / group_n[g], 3)
    omit.to_csv(out("entity_presence_by_group.csv"))

    # ---- plotly heatmap ----
    try:
        import plotly.graph_objects as go
        fig = go.Figure(go.Heatmap(
            z=share[groups].values, x=groups, y=[nname.get(n, n) for n in narratives],
            colorscale="Blues", zmin=0, zmax=1,
            text=share[groups].round(2).values, texttemplate="%{text}"))
        fig.update_layout(title=f"Narrative share within media group — {args.slug}",
                          xaxis_title="media group", yaxis_title="narrative", height=520)
        fig.write_html(out("narrative_heatmap.html"))
    except Exception as e:  # noqa: BLE001
        print("heatmap skipped:", e)

    # ---- deterministic markdown report ----
    render_report(args.slug, df, share, js, sem, epi, flips, lex, cause, group_n, nname, narratives,
                  groups)
    print(f"\nwrote {len(list(OUTPUTS.glob(f'event_{args.slug}_*')))} files to {OUTPUTS}/ and "
          f"a report to {REPORTS}/event_{args.slug}_framing.md")


def render_report(slug, df, share, js, sem, epi, flips, lex, cause, group_n, nname, narratives,
                  groups):
    L = []
    L.append(f"# Framing comparison — {slug}\n")
    L.append(f"_{len(df)} on-event messages across {len(groups)} media groups. "
             "Shares are within-group; groups with n<30 are directional only._\n")

    L.append("## Coverage volume\n")
    for g in sorted(groups, key=lambda x: -group_n[x]):
        flag = "  ⚠️ directional only" if group_n[g] < MIN_N else ""
        L.append(f"- **{g}** — {group_n[g]} messages{flag}")

    L.append("\n## Dominant narrative per group\n")
    for g in sorted(groups, key=lambda x: -group_n[x]):
        col = share[g].sort_values(ascending=False)
        top = col.index[0]
        L.append(f"- **{g}**: {nname.get(top, top)} ({col.iloc[0]:.0%})"
                 + (f", then {nname.get(col.index[1], col.index[1])} ({col.iloc[1]:.0%})"
                    if len(col) > 1 and col.iloc[1] > 0 else ""))

    L.append("\n## Most divergent group pairs (JS distance, 0–1)\n")
    pairs = [(a, b, js.loc[a, b]) for a, b in combinations(groups, 2)]
    for a, b, d in sorted(pairs, key=lambda x: -x[2])[:5]:
        L.append(f"- {a} ↔ {b}: **{d:.2f}**")

    L.append("\n## Entity role flips (same actor, different role across groups)\n")
    if len(flips):
        contra = flips[flips.opposed_contradiction] if "opposed_contradiction" in flips else flips
        show = contra if len(contra) else flips
        for _, row in show.head(8).iterrows():
            gcols = [c for c in row.index if c not in
                     ("entity", "n_groups", "opposed_contradiction")]
            assigns = "; ".join(f"{c}: {row[c]}" for c in gcols if isinstance(row[c], str))
            mark = "🔴 " if row.get("opposed_contradiction") else ""
            L.append(f"- {mark}**{row['entity']}** — {assigns}")
    else:
        L.append("- (none detected)")

    L.append("\n## Epistemic stance (share of messages)\n")
    L.append(df_to_md(epi))

    L.append("\n## Semetko generic frames (prevalence by group)\n")
    L.append(df_to_md(sem))

    L.append("\n## Signature action labels by group (top terms)\n")
    for g in sorted(groups, key=lambda x: -group_n[x]):
        terms = ", ".join(f"«{t}»" for (t, _v), _c in lex.get(g, Counter()).most_common(6))
        if terms:
            L.append(f"- **{g}**: {terms}")

    L.append("\n## Who each group blames (top cause entity)\n")
    for g in sorted(groups, key=lambda x: -group_n[x]):
        c = cause.get(g, Counter())
        if c:
            ce, n = c.most_common(1)[0]
            L.append(f"- **{g}**: {ce} ({n / group_n[g]:.0%} of msgs name a cause as {ce})")

    (REPORTS / f"event_{slug}_framing.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
