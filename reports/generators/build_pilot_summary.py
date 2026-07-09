#!/usr/bin/env python3
"""Build a compact, evidence-backed summary of the exploratory pilot.

Inputs are the durable pilot artifacts:
- data/interim/event_*_framing.jsonl for message-level framing labels.
- data/processed/event_*_manifest.json for event names and retrieval counts.
- outputs/event_kursk_2025w11_* for the one completed narrative comparison.

Outputs:
- reports/pilot_analysis_summary.md
- reports/pilot_analysis_charts.html
- outputs/pilot_summary/*.csv
"""

from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_INTERIM = ROOT / "data" / "interim"
DATA_PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
PILOT_OUT = OUTPUTS / "pilot_summary"
REPORTS = ROOT / "reports"

MIN_GROUP_N = 15

GROUP_ORDER = [
    "State agencies",
    "Federal TV and state broadcasters",
    "Pro-government online media",
    "Mainstream business and general media",
    "Independent and exile media",
    "War and military channels",
]

GROUP_SHORT = {
    "State agencies": "State agencies",
    "Federal TV and state broadcasters": "Federal TV",
    "Pro-government online media": "Pro-gov online",
    "Mainstream business and general media": "Mainstream",
    "Independent and exile media": "Independent",
    "War and military channels": "War channels",
}

SEMETKO = [
    "conflict",
    "responsibility",
    "morality",
    "human_interest",
    "economic_consequences",
]

EVENT_LABEL = {
    "brics_kazan_2024w43": "BRICS Kazan",
    "dc_aircrash_2025w05": "Washington air crash",
    "kursk_2025w11": "Kursk / Sudzha",
    "kursk_2025w11_qwen3": "Kursk / Sudzha (Qwen3 retrieval rerun)",
    "prices_2025w11": "Price rises",
    "putin_direct_line_2024w51": "Putin Direct Line",
    "putin_trump_call_2025w08": "Putin-Trump call",
    "sevastopol_beach_2024w26": "Sevastopol beach attack",
    "trump_inauguration_2025w04": "Trump inauguration",
    "trump_zelensky_2025w10": "Trump-Zelensky",
    "us_russia_contacts_2025w09": "Russia-US contacts",
}

EVENT_ORDER = [
    "dc_aircrash_2025w05",
    "putin_trump_call_2025w08",
    "us_russia_contacts_2025w09",
    "trump_zelensky_2025w10",
    "kursk_2025w11",
    "prices_2025w11",
]

KEY_ACTORS = {
    "kursk_2025w11": ["Russian Armed Forces", "Ukrainian Armed Forces"],
    "trump_zelensky_2025w10": ["Volodymyr Zelenskyy", "Donald Trump"],
}


def pct(x: float | None, digits: int = 0) -> str:
    if x is None or pd.isna(x):
        return "-"
    return f"{x * 100:.{digits}f}%"


def num(x: float | int | None, digits: int = 2) -> str:
    if x is None or pd.isna(x):
        return "-"
    if isinstance(x, int) or float(x).is_integer():
        return f"{int(x)}"
    return f"{x:.{digits}f}"


def md_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    headers = [label for _, label in columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        cells = [str(row.get(key, "")) for key, _ in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def load_manifests() -> dict[str, dict]:
    manifests = {}
    for path in sorted(DATA_PROCESSED.glob("event_*_manifest.json")):
        slug = path.name.removeprefix("event_").removesuffix("_manifest.json")
        manifests[slug] = json.loads(path.read_text(encoding="utf-8"))
    return manifests


def framed_records() -> dict[str, list[dict]]:
    events = {}
    for path in sorted(DATA_INTERIM.glob("event_*_framing.jsonl")):
        slug = path.name.removeprefix("event_").removesuffix("_framing.jsonl")
        rows = [r for r in load_jsonl(path) if r.get("on_event", True)]
        events[slug] = rows
    return events


def group_counts(events: dict[str, list[dict]]) -> pd.DataFrame:
    rows = []
    for slug, recs in events.items():
        counts = Counter(r.get("media_group") for r in recs)
        for group in GROUP_ORDER:
            rows.append({
                "event_slug": slug,
                "event": EVENT_LABEL.get(slug, slug),
                "media_group": group,
                "messages": counts.get(group, 0),
            })
    return pd.DataFrame(rows)


def event_inventory(events: dict[str, list[dict]], manifests: dict[str, dict]) -> pd.DataFrame:
    framed = set(events)
    rows = []
    for slug in sorted(manifests):
        manifest = manifests[slug]
        counts = manifest.get("counts", {})
        event = manifest.get("event", {})
        group_n = Counter(r.get("media_group") for r in events.get(slug, []))
        if slug in framed:
            status = "framed"
        elif slug.endswith("_qwen3"):
            status = "retrieval rerun only"
        else:
            status = "dataset only"
        rows.append({
            "event_slug": slug,
            "event_name": event.get("name", ""),
            "short_name": EVENT_LABEL.get(slug, slug),
            "fom_pct": event.get("fom_percentage", ""),
            "match_start": manifest.get("window", {}).get("match_start", ""),
            "match_end_exclusive": manifest.get("window", {}).get("match_end_exclusive", ""),
            "retrieved_kept": counts.get("kept", ""),
            "framed_on_event": len(events.get(slug, [])) if slug in framed else 0,
            "framing_status": status,
            "groups_n_ge_15": sum(1 for n in group_n.values() if n >= MIN_GROUP_N),
            "groups_total": len([n for n in group_n.values() if n > 0]),
        })
    return pd.DataFrame(rows)


def metric_tables(events: dict[str, list[dict]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    message_rows = []
    action_rows = []
    actor_rows = []

    for slug, recs in events.items():
        by_group = defaultdict(list)
        for rec in recs:
            by_group[rec.get("media_group")].append(rec)

        for group in GROUP_ORDER:
            group_recs = by_group.get(group, [])
            n_messages = len(group_recs)
            if not n_messages:
                continue

            epi = Counter(r.get("epistemic_status") for r in group_recs)
            row = {
                "event_slug": slug,
                "event": EVENT_LABEL.get(slug, slug),
                "media_group": group,
                "group_short": GROUP_SHORT[group],
                "n_messages": n_messages,
                "asserted_share": epi.get("asserted", 0) / n_messages,
                "attributed_share": epi.get("attributed", 0) / n_messages,
                "hedged_or_questioned_share": (
                    epi.get("hedged", 0) + epi.get("questioned", 0) + epi.get("denied", 0)
                ) / n_messages,
                "treatment_present_share": sum(1 for r in group_recs if r.get("treatment"))
                / n_messages,
            }
            for frame in SEMETKO:
                row[f"{frame}_share"] = sum(
                    1 for r in group_recs if (r.get("semetko") or {}).get(frame)
                ) / n_messages
            message_rows.append(row)

            labels = [
                label
                for r in group_recs
                for label in (r.get("action_labels") or [])
                if label.get("valence")
            ]
            val = Counter(label.get("valence") for label in labels)
            action_rows.append({
                "event_slug": slug,
                "event": EVENT_LABEL.get(slug, slug),
                "media_group": group,
                "group_short": GROUP_SHORT[group],
                "n_messages": n_messages,
                "n_action_labels": len(labels),
                "positive_action_label_share": (
                    val.get("positive", 0) / len(labels) if labels else math.nan
                ),
                "negative_action_label_share": (
                    val.get("negative", 0) / len(labels) if labels else math.nan
                ),
                "neutral_action_label_share": (
                    val.get("neutral", 0) / len(labels) if labels else math.nan
                ),
            })

        for actor in KEY_ACTORS.get(slug, []):
            for group in GROUP_ORDER:
                polarities = []
                asserted_polarities = []
                for rec in by_group.get(group, []):
                    is_asserted = rec.get("epistemic_status") == "asserted"
                    for moral in rec.get("moral_evaluation") or []:
                        if moral.get("entity") != actor:
                            continue
                        pol = moral.get("polarity")
                        if isinstance(pol, (int, float)):
                            pol = max(-2, min(2, pol))
                            polarities.append(pol)
                            if is_asserted:
                                asserted_polarities.append(pol)
                if polarities:
                    actor_rows.append({
                        "event_slug": slug,
                        "event": EVENT_LABEL.get(slug, slug),
                        "actor": actor,
                        "media_group": group,
                        "group_short": GROUP_SHORT[group],
                        "n_role_assignments": len(polarities),
                        "mean_polarity_all_mentions": sum(polarities) / len(polarities),
                        "n_asserted_role_assignments": len(asserted_polarities),
                        "mean_polarity_asserted_only": (
                            sum(asserted_polarities) / len(asserted_polarities)
                            if asserted_polarities else math.nan
                        ),
                    })

    return pd.DataFrame(message_rows), pd.DataFrame(action_rows), pd.DataFrame(actor_rows)


def spread_table(message_metrics: pd.DataFrame, action_metrics: pd.DataFrame) -> pd.DataFrame:
    dims = [
        ("asserted_share", "Asserted in own voice", "message"),
        ("attributed_share", "Attributed to a source", "message"),
        ("morality_share", "Morality frame", "message"),
        ("human_interest_share", "Human-interest frame", "message"),
        ("economic_consequences_share", "Economic-consequences frame", "message"),
        ("responsibility_share", "Responsibility frame", "message"),
        ("conflict_share", "Conflict frame", "message"),
        ("treatment_present_share", "Prescribes remedy/action", "message"),
    ]
    rows = []

    for slug in EVENT_ORDER:
        msg = message_metrics[
            (message_metrics.event_slug == slug) & (message_metrics.n_messages >= MIN_GROUP_N)
        ]
        if len(msg) >= 2:
            for col, label, base in dims:
                values = msg.dropna(subset=[col])
                high = values.loc[values[col].idxmax()]
                low = values.loc[values[col].idxmin()]
                rows.append({
                    "event_slug": slug,
                    "event": EVENT_LABEL.get(slug, slug),
                    "dimension": label,
                    "base": base,
                    "groups_compared": len(values),
                    "high_group": high.group_short,
                    "high_value": high[col],
                    "high_n": int(high.n_messages),
                    "low_group": low.group_short,
                    "low_value": low[col],
                    "low_n": int(low.n_messages),
                    "spread_pp": (high[col] - low[col]) * 100,
                })

        act = action_metrics[
            (action_metrics.event_slug == slug)
            & (action_metrics.n_messages >= MIN_GROUP_N)
            & (action_metrics.n_action_labels >= 20)
        ].dropna(subset=["positive_action_label_share"])
        if len(act) >= 2:
            high = act.loc[act.positive_action_label_share.idxmax()]
            low = act.loc[act.positive_action_label_share.idxmin()]
            rows.append({
                "event_slug": slug,
                "event": EVENT_LABEL.get(slug, slug),
                "dimension": "Positive loaded action terms",
                "base": "action label",
                "groups_compared": len(act),
                "high_group": high.group_short,
                "high_value": high.positive_action_label_share,
                "high_n": int(high.n_action_labels),
                "low_group": low.group_short,
                "low_value": low.positive_action_label_share,
                "low_n": int(low.n_action_labels),
                "spread_pp": (
                    high.positive_action_label_share - low.positive_action_label_share
                ) * 100,
            })

    df = pd.DataFrame(rows)
    return df.sort_values(["event_slug", "spread_pp"], ascending=[True, False])


def kursk_narrative_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ci_path = OUTPUTS / "event_kursk_2025w11_narrative_by_group_ci.csv"
    js_path = OUTPUTS / "event_kursk_2025w11_group_js_divergence.csv"
    if not ci_path.exists() or not js_path.exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    ci = pd.read_csv(ci_path)
    ci["group_short"] = ci["media_group"].map(GROUP_SHORT)
    ci["share_pct"] = ci["share"] * 100
    ci["ci"] = ci.apply(lambda r: f"{r.share * 100:.1f}% ({r.ci_lo * 100:.1f}-{r.ci_hi * 100:.1f})", axis=1)

    js = pd.read_csv(js_path, index_col=0)
    pairs = []
    for a, b in combinations(js.index, 2):
        pairs.append({
            "group_a": GROUP_SHORT.get(a, a),
            "group_b": GROUP_SHORT.get(b, b),
            "js_distance": float(js.loc[a, b]),
        })
    pairs_df = pd.DataFrame(pairs).sort_values("js_distance", ascending=False)
    mean_df = (
        pd.concat([
            pairs_df.rename(columns={"group_a": "group"})[["group", "js_distance"]],
            pairs_df.rename(columns={"group_b": "group"})[["group", "js_distance"]],
        ])
        .groupby("group", as_index=False)
        .agg(mean_js_distance=("js_distance", "mean"), max_pair_distance=("js_distance", "max"))
        .sort_values("mean_js_distance", ascending=False)
    )
    return ci, pairs_df, mean_df


def color_scale(value: float, max_value: float = 1.0) -> str:
    if value is None or pd.isna(value):
        return "#f2f4f7"
    t = min(max(value / max_value, 0), 1)
    r = round(244 - 139 * t)
    g = round(248 - 78 * t)
    b = round(252 - 29 * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def heatmap_svg(
    matrix: pd.DataFrame,
    path: Path,
    title: str,
    max_value: float = 1.0,
    value_fmt=pct,
) -> None:
    row_h = 32
    col_w = 110
    label_w = 170
    top = 78
    width = label_w + col_w * len(matrix.columns) + 30
    height = top + row_h * len(matrix.index) + 36
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
        'font-size:12px;fill:#172033}.title{font-size:17px;font-weight:700}'
        '.axis{font-size:11px;fill:#445}.celltext{font-size:11px;font-weight:600}</style>',
        f'<text x="12" y="24" class="title">{html.escape(title)}</text>',
    ]
    for j, col in enumerate(matrix.columns):
        x = label_w + j * col_w + col_w / 2
        pieces.append(
            f'<text x="{x}" y="58" class="axis" text-anchor="middle">'
            f'{html.escape(str(col))}</text>'
        )
    for i, idx in enumerate(matrix.index):
        y = top + i * row_h
        pieces.append(
            f'<text x="12" y="{y + 21}" text-anchor="start">'
            f'{html.escape(str(idx))}</text>'
        )
        for j, col in enumerate(matrix.columns):
            x = label_w + j * col_w
            val = matrix.loc[idx, col]
            fill = color_scale(float(val), max_value) if not pd.isna(val) else "#f2f4f7"
            pieces.append(
                f'<rect x="{x}" y="{y}" width="{col_w - 2}" height="{row_h - 2}" '
                f'rx="4" fill="{fill}"/>'
            )
            pieces.append(
                f'<text x="{x + col_w / 2 - 1}" y="{y + 20}" class="celltext" '
                f'text-anchor="middle">{html.escape(value_fmt(val))}</text>'
            )
    pieces.append("</svg>")
    path.write_text("\n".join(pieces), encoding="utf-8")


def bar_svg(
    rows: pd.DataFrame,
    path: Path,
    title: str,
    label_col: str,
    value_col: str,
    max_value: float,
    value_fmt=pct,
) -> None:
    row_h = 30
    label_w = 205
    bar_w = 360
    top = 45
    width = label_w + bar_w + 85
    height = top + row_h * len(rows) + 25
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;'
        'font-size:12px;fill:#172033}.title{font-size:17px;font-weight:700}'
        '.val{font-size:12px;font-weight:600}</style>',
        f'<text x="12" y="24" class="title">{html.escape(title)}</text>',
    ]
    for i, row in rows.reset_index(drop=True).iterrows():
        y = top + i * row_h
        value = float(row[value_col])
        width_bar = 0 if max_value == 0 else bar_w * value / max_value
        pieces.append(
            f'<text x="12" y="{y + 18}">{html.escape(str(row[label_col]))}</text>'
        )
        pieces.append(
            f'<rect x="{label_w}" y="{y + 5}" width="{bar_w}" height="16" '
            'rx="4" fill="#edf2f7"/>'
        )
        pieces.append(
            f'<rect x="{label_w}" y="{y + 5}" width="{width_bar}" height="16" '
            'rx="4" fill="#4f86c6"/>'
        )
        pieces.append(
            f'<text x="{label_w + bar_w + 12}" y="{y + 18}" class="val">'
            f'{html.escape(value_fmt(value))}</text>'
        )
    pieces.append("</svg>")
    path.write_text("\n".join(pieces), encoding="utf-8")


def write_charts(
    counts: pd.DataFrame,
    message_metrics: pd.DataFrame,
    action_metrics: pd.DataFrame,
    actor_metrics: pd.DataFrame,
    kursk_ci: pd.DataFrame,
) -> list[Path]:
    chart_paths: list[Path] = []

    counts_pivot = (
        counts.pivot(index="event", columns="media_group", values="messages")
        .reindex([EVENT_LABEL[s] for s in EVENT_ORDER])
        .rename(columns=GROUP_SHORT)
    )
    path = PILOT_OUT / "chart_event_group_counts.svg"
    heatmap_svg(counts_pivot, path, "On-event framed messages by event and media group",
                max_value=max(1, counts_pivot.max().max()), value_fmt=lambda v: str(int(v)))
    chart_paths.append(path)

    asserted = (
        message_metrics.pivot(index="event", columns="media_group", values="asserted_share")
        .reindex([EVENT_LABEL[s] for s in EVENT_ORDER])
        .rename(columns=GROUP_SHORT)
    )
    path = PILOT_OUT / "chart_asserted_share.svg"
    heatmap_svg(asserted, path, "Share of messages asserted in the outlet's own voice")
    chart_paths.append(path)

    positive = (
        action_metrics.pivot(
            index="event", columns="media_group", values="positive_action_label_share"
        )
        .reindex([EVENT_LABEL[s] for s in EVENT_ORDER])
        .rename(columns=GROUP_SHORT)
    )
    path = PILOT_OUT / "chart_positive_action_terms.svg"
    heatmap_svg(positive, path, "Share of loaded action terms marked positive")
    chart_paths.append(path)

    if not kursk_ci.empty:
        narrative = (
            kursk_ci.pivot(index="narrative", columns="group_short", values="share")
            .fillna(0)
            .reindex(columns=[GROUP_SHORT[g] for g in GROUP_ORDER])
        )
        path = PILOT_OUT / "chart_kursk_narrative_shares.svg"
        heatmap_svg(narrative, path, "Kursk narrative share within each media group")
        chart_paths.append(path)

        failed = kursk_ci[
            kursk_ci.narrative_id == "potok_failed_or_detected_attack"
        ].sort_values("share", ascending=True)
        path = PILOT_OUT / "chart_kursk_failed_potok_share.svg"
        bar_svg(
            failed,
            path,
            "Kursk: share of 'Pipeline infiltration as failed Russian attack'",
            "group_short",
            "share",
            max_value=max(0.2, failed.share.max()),
        )
        chart_paths.append(path)

    kursk_actor = actor_metrics[
        actor_metrics.event_slug.eq("kursk_2025w11")
        & actor_metrics.actor.isin(KEY_ACTORS["kursk_2025w11"])
    ].copy()
    if not kursk_actor.empty:
        matrix = (
            kursk_actor.pivot(
                index="actor", columns="group_short", values="mean_polarity_all_mentions"
            )
            .reindex(KEY_ACTORS["kursk_2025w11"])
            .reindex(columns=[GROUP_SHORT[g] for g in GROUP_ORDER])
        )
        # Convert -2..+2 to 0..1 for color, but keep text as polarity.
        color_matrix = (matrix + 2) / 4
        path = PILOT_OUT / "chart_kursk_actor_polarity.svg"
        heatmap_svg(
            color_matrix,
            path,
            "Kursk actor evaluation by group (cell text: mean polarity, -2 to +2)",
            value_fmt=lambda v: f"{(float(v) * 4 - 2):+.1f}",
        )
        chart_paths.append(path)

    return chart_paths


def write_html_charts(chart_paths: list[Path]) -> None:
    blocks = []
    for path in chart_paths:
        svg = path.read_text(encoding="utf-8")
        blocks.append(f"<section>{svg}</section>")
    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Pilot analysis charts</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 28px; color: #172033; background: #fff; }}
    section {{ margin: 0 0 34px; }}
  </style>
</head>
<body>
  <h1>Pilot analysis charts</h1>
  {''.join(blocks)}
</body>
</html>
"""
    (REPORTS / "pilot_analysis_charts.html").write_text(html_doc, encoding="utf-8")


def write_markdown_report(
    inventory: pd.DataFrame,
    counts: pd.DataFrame,
    message_metrics: pd.DataFrame,
    action_metrics: pd.DataFrame,
    actor_metrics: pd.DataFrame,
    spreads: pd.DataFrame,
    kursk_ci: pd.DataFrame,
    kursk_pairs: pd.DataFrame,
    kursk_mean: pd.DataFrame,
    chart_paths: list[Path],
) -> None:
    lines = [
        "# Pilot analysis summary",
        "",
        "This is a re-read of the exploratory pilot from the saved local outputs. "
        "The report separates message-level framing results from event-dataset-only outputs. "
        "Percentages are within a media group unless a table says otherwise.",
        "",
        "## Evidence base",
        "",
    ]

    inv_show = inventory.copy()
    inv_show["window"] = inv_show["match_start"] + " to " + inv_show["match_end_exclusive"]
    inv_rows = []
    status_order = {"framed": 0, "retrieval rerun only": 1, "dataset only": 2}
    inv_show["status_order"] = inv_show["framing_status"].map(status_order).fillna(9)
    for _, row in inv_show.sort_values(["status_order", "short_name"]).iterrows():
        inv_rows.append({
            "event": row.short_name,
            "status": row.framing_status,
            "retrieved": row.retrieved_kept,
            "framed": row.framed_on_event,
            "groups n>=15": row.groups_n_ge_15,
            "window": row.window,
        })
    lines.append(md_table(inv_rows, [
        ("event", "Event"),
        ("status", "Status"),
        ("retrieved", "Retrieved kept"),
        ("framed", "Framed on-event"),
        ("groups n>=15", "Framed groups with n>=15"),
        ("window", "Date window"),
    ]))
    lines.append("")
    lines.append(
        "Interpretation rule used here: I only compare media groups inside an event when at least "
        f"two groups have {MIN_GROUP_N}+ framed messages. Smaller groups are shown as evidence "
        "of coverage volume, not as stable group-level findings."
    )
    lines.append("")
    lines.append("## Charts")
    lines.append("")
    for path in chart_paths:
        rel = path.relative_to(REPORTS.parent)
        title = path.stem.replace("_", " ")
        lines.append(f"![{title}](../{rel})")
        lines.append("")

    lines.append("## Main results with comparison bases")
    lines.append("")
    top_spreads = (
        spreads[spreads.groups_compared >= 2]
        .sort_values("spread_pp", ascending=False)
        .head(12)
        .copy()
    )
    spread_rows = []
    for _, row in top_spreads.iterrows():
        spread_rows.append({
            "event": row.event,
            "dimension": row.dimension,
            "base": row.base,
            "groups": int(row.groups_compared),
            "high": f"{row.high_group}: {pct(row.high_value)} (n={row.high_n})",
            "low": f"{row.low_group}: {pct(row.low_value)} (n={row.low_n})",
            "spread": f"{row.spread_pp:.0f} pp",
        })
    lines.append(md_table(spread_rows, [
        ("event", "Event"),
        ("dimension", "Dimension"),
        ("base", "Base"),
        ("groups", "Groups compared"),
        ("high", "Highest group"),
        ("low", "Lowest group"),
        ("spread", "Spread"),
    ]))
    lines.append("")
    lines.append(
        "Among the metrics calculated here, assertion and attribution produce several of the "
        "largest within-event spreads. This means the groups often differ in whether the "
        "message speaks in the outlet's own voice or attributes the claim to someone else. "
        "For example, in Kursk the asserted-share spread is 58 percentage points: War channels "
        "71% versus State agencies 13%, across all six groups. In Trump-Zelensky the same "
        "measure spreads by 50 points: War channels 56% versus State agencies 6%."
    )
    lines.append("")
    lines.append(
        "Word choice separates Kursk strongly. Positive loaded action terms range from "
        "68% in Federal TV to 29% in Independent media, using action-label assignments as the "
        "base. That is a 39-point spread, not just a qualitative impression."
    )
    lines.append("")

    lines.append("## Kursk narrative comparison")
    lines.append("")
    if kursk_pairs.empty:
        lines.append("The Kursk narrative comparison files were not present, so this section is skipped.")
    else:
        pair_values = kursk_pairs.js_distance.tolist()
        lines.append(
            "For Kursk only, the narrative comparison uses Jensen-Shannon distance over the five "
            "induced narrative shares. The scale is 0 to 1: 0 means two groups have identical "
            "narrative distributions; 1 would mean no overlap. There are 15 group pairs. "
            f"The observed range is {min(pair_values):.3f} to {max(pair_values):.3f}, "
            f"with median {pd.Series(pair_values).median():.3f}."
        )
        lines.append("")
        pair_rows = []
        for _, row in kursk_pairs.head(8).iterrows():
            pair_rows.append({
                "pair": f"{row.group_a} vs {row.group_b}",
                "js": f"{row.js_distance:.3f}",
            })
        lines.append(md_table(pair_rows, [
            ("pair", "Pair"),
            ("js", "JS distance"),
        ]))
        lines.append("")
        mean_rows = []
        for _, row in kursk_mean.iterrows():
            mean_rows.append({
                "group": row.group,
                "mean": f"{row.mean_js_distance:.3f}",
                "max": f"{row.max_pair_distance:.3f}",
            })
        lines.append(md_table(mean_rows, [
            ("group", "Group"),
            ("mean", "Mean distance to other groups"),
            ("max", "Largest pair distance"),
        ]))
        lines.append("")
        lines.append(
            "So the exact Kursk statement is: Independent media has the highest mean distance "
            f"to the other groups ({kursk_mean.iloc[0].mean_js_distance:.3f}). Its largest pair "
            "distance is against State agencies (0.308). This is the largest pair distance among "
            "the 15 Kursk group pairs, but it is a moderate distribution difference, not a total "
            "separation."
        )
        lines.append("")

        failed = kursk_ci[kursk_ci.narrative_id == "potok_failed_or_detected_attack"].copy()
        failed = failed.sort_values("share", ascending=False)
        failed_rows = []
        for _, row in failed.iterrows():
            failed_rows.append({
                "group": row.group_short,
                "n": int(row.n),
                "share with CI": row.ci,
            })
        lines.append(
            "The 'Pipeline infiltration as failed Russian attack' frame is the clearest specific "
            "Kursk counter-frame. The table shows exactly 'more than what':"
        )
        lines.append("")
        lines.append(md_table(failed_rows, [
            ("group", "Group"),
            ("n", "Messages"),
            ("share with CI", "Share, 95% bootstrap CI"),
        ]))
        lines.append("")

    lines.append("## Actor evaluation checks")
    lines.append("")
    actor_rows = []
    for _, row in actor_metrics[
        actor_metrics.event_slug.isin(["kursk_2025w11", "trump_zelensky_2025w10"])
    ].sort_values(["event", "actor", "mean_polarity_all_mentions"], ascending=[True, True, False]).iterrows():
        actor_rows.append({
            "event": row.event,
            "actor": row.actor,
            "group": row.group_short,
            "n": int(row.n_role_assignments),
            "mean polarity": f"{row.mean_polarity_all_mentions:+.2f}",
            "asserted-only n": int(row.n_asserted_role_assignments),
            "asserted-only mean": (
                "-"
                if pd.isna(row.mean_polarity_asserted_only)
                else f"{row.mean_polarity_asserted_only:+.2f}"
            ),
        })
    lines.append(md_table(actor_rows, [
        ("event", "Event"),
        ("actor", "Actor"),
        ("group", "Group"),
        ("n", "Role mentions"),
        ("mean polarity", "Mean polarity"),
        ("asserted-only n", "Asserted-only role mentions"),
        ("asserted-only mean", "Asserted-only mean"),
    ]))
    lines.append("")
    lines.append(
        "This table is included because role labels alone can mislead. A role may appear in quoted "
        "speech or in a negative context. The asserted-only columns show how much evidence remains "
        "when we restrict to messages that state the core claim in the outlet's own voice."
    )
    lines.append("")

    lines.append("## What the pilot supports")
    lines.append("")
    lines.append(
        "1. The pilot supports cross-media comparison for high-volume, clear event windows. Kursk "
        "and Trump-Zelensky are the strongest examples because all six groups have 15+ messages."
    )
    lines.append(
        "2. The clearest measurable separators are assertion/attribution, loaded action terms, "
        "moral framing, and actor polarity. These can be compared across events."
    )
    lines.append(
        "3. Induced narrative labels are useful for reading one event, but they should be treated "
        "as event-specific. For cross-event dashboards, fixed fields are safer: epistemic status, "
        "Semetko frames, action-label valence, cause entity, and actor polarity."
    )
    lines.append(
        "4. Small or skewed events, such as Price rises and Washington air crash, should not be "
        "used for strong media-type conclusions yet. They are better treated as schema tests or "
        "retrieval checks."
    )
    lines.append("")

    lines.append("## Output files")
    lines.append("")
    lines.append("- Tables: `outputs/pilot_summary/*.csv`")
    lines.append("- Charts: `outputs/pilot_summary/*.svg`")
    lines.append("- Chart page: `reports/pilot_analysis_charts.html`")
    lines.append("")

    (REPORTS / "pilot_analysis_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    PILOT_OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    manifests = load_manifests()
    events = framed_records()

    inventory = event_inventory(events, manifests)
    counts = group_counts(events)
    message_metrics, action_metrics, actor_metrics = metric_tables(events)
    spreads = spread_table(message_metrics, action_metrics)
    kursk_ci, kursk_pairs, kursk_mean = kursk_narrative_tables()

    inventory.to_csv(PILOT_OUT / "event_inventory.csv", index=False)
    counts.to_csv(PILOT_OUT / "event_group_message_counts.csv", index=False)
    message_metrics.to_csv(PILOT_OUT / "message_level_metrics_by_group.csv", index=False)
    action_metrics.to_csv(PILOT_OUT / "action_label_metrics_by_group.csv", index=False)
    actor_metrics.to_csv(PILOT_OUT / "actor_polarity_by_group.csv", index=False)
    spreads.to_csv(PILOT_OUT / "largest_group_spreads.csv", index=False)
    if not kursk_ci.empty:
        kursk_ci.to_csv(PILOT_OUT / "kursk_narrative_shares.csv", index=False)
        kursk_pairs.to_csv(PILOT_OUT / "kursk_js_pair_distances.csv", index=False)
        kursk_mean.to_csv(PILOT_OUT / "kursk_mean_js_by_group.csv", index=False)

    chart_paths = write_charts(counts, message_metrics, action_metrics, actor_metrics, kursk_ci)
    write_html_charts(chart_paths)
    write_markdown_report(
        inventory,
        counts,
        message_metrics,
        action_metrics,
        actor_metrics,
        spreads,
        kursk_ci,
        kursk_pairs,
        kursk_mean,
        chart_paths,
    )

    print(f"Wrote {REPORTS / 'pilot_analysis_summary.md'}")
    print(f"Wrote {REPORTS / 'pilot_analysis_charts.html'}")
    print(f"Wrote {PILOT_OUT}")


if __name__ == "__main__":
    main()
