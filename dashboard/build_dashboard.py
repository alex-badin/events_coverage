#!/usr/bin/env python3
"""Build an offline dashboard or a static web release from one data export."""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "dashboard" / "coverage_dashboard_template.html"
DATA_JSON = PROJECT_ROOT / "outputs" / "dashboard_exports" / "dashboard_data.json"
OUTPUT_HTML = PROJECT_ROOT / "outputs" / "dashboard_exports" / "coverage_dashboard.html"

PLACEHOLDER = "__DATA__"
TABLE_FIELDS = (
    "event_id", "media_group", "media_group_key", "matched_posts",
    "matched_posts_per_1000_published", "posts_published_in_window",
)
EVENT_FIELDS = (
    "event_id", "matched_posts", "sources_covering", "sources_active", "groups_covering",
    "groups_active", "match_start", "match_end_exclusive", "retriever", "rerank_model",
    "rerank_threshold", "candidates_reranked", "searchable_share_of_window",
    "searchable_posts_in_window", "posts_published_in_window", "median_relevance_score",
    "min_relevance_score", "built_at", "standard_relevance_cutoff",
)


def compact_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def html_with_data(template: str, data: str) -> str:
    # Keep HTML markup and JavaScript line separators inside JSON strings.
    escaped = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return template.replace(PLACEHOLDER, escaped, 1)


def write_web_file(path: Path, body: str) -> int:
    raw = body.encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    path.write_bytes(raw)
    path.with_suffix(path.suffix + ".gz").write_bytes(compressed)
    return len(compressed)


def build_web(template: str, data: dict, out: Path, release_id: str) -> None:
    rows = data["week_events"]
    ids = {row["event_id"] for row in rows}
    if len(ids) != len(rows) or not all(re.fullmatch(r"[0-9a-f]{32}", key) for key in ids):
        raise ValueError("Expected one unique, 32-character event ID per survey row.")
    specific = [row for row in rows if row["event_kind"] == "specific event"]
    measured = {row["event_id"] for row in rows if row["coverage_status"] == "measured"}
    details = defaultdict(dict)
    for name in ("groups", "daily", "terms", "posts"):
        for row in data[name]:
            if row["event_id"] not in ids:
                raise ValueError(f"{name} refers to an event outside the survey rows.")
            details[row["event_id"]].setdefault(name, []).append(row)
    for event in data["events"]:
        if event["event_id"] not in ids:
            raise ValueError("An event overview has no matching survey row.")
        details[event["event_id"]]["overview"] = event

    index_rows = []
    for row in rows:
        item = dict(row)
        quotes = item.pop("quotes", [])
        key = row["event_id"]
        if quotes or key in measured:
            details[key]["quotes"] = quotes
        item["has_details"] = key in details
        index_rows.append(item)

    events_dir = out / "data" / "events"
    out.mkdir(parents=True)
    events_dir.mkdir(parents=True)
    largest = 0
    for key, detail in details.items():
        largest = max(largest, write_web_file(events_dir / f"{key}.json", compact_json(detail)))

    index = {
        "week_events": index_rows,
        "events": [{key: row[key] for key in EVENT_FIELDS} for row in data["events"]],
        "groups": [{key: row[key] for key in TABLE_FIELDS} for row in data["groups"]],
        "theme_weeks": data["theme_weeks"],
        "themes": data["themes"],
        "scope_coverage": data["scope_coverage"],
    }
    index_bytes = write_web_file(out / "data" / "index.json", compact_json(index))
    # The chart can show shares and counts before the wording and tooltips arrive.
    first = {
        "weeks": data["weeks"],
        "meta": data["meta"],
        "themes": [{key: val for key, val in row.items() if key not in ("definition", "label_ru")}
                   for row in data["themes"]],
        "theme_weeks": [{key: val for key, val in row.items()
                         if key not in ("top_event_name", "top_event_share", "n_top_events")}
                        for row in data["theme_weeks"]],
        "scope_coverage": [row for row in data["scope_coverage"] if row["scope_type"] == "all"],
    }
    first["web"] = {
        "base": f"/versions/{release_id}/data/",
        "specific_count": len(specific),
        "measured_count": len(measured),
        "unmeasured_after_w20": sum(
            row["fom_year"] * 100 + row["fom_week"] > 202620 and row["event_id"] not in measured
            for row in specific
        ),
        "word_event_count": len({row["event_id"] for row in data["terms"]}),
    }
    first_bytes = write_web_file(out / "index.html", html_with_data(template, compact_json(first)))
    print(f"Web release {release_id}: {first_bytes:,} B initial, {index_bytes:,} B table, "
          f"{len(details):,} event files (largest {largest:,} B), gzip sizes.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_JSON)
    parser.add_argument("--web-dir", type=Path, help="Build a web release in a new directory.")
    parser.add_argument("--release-id", help="Required with --web-dir. Used in the public data URLs.")
    args = parser.parse_args()
    if bool(args.web_dir) != bool(args.release_id):
        parser.error("--web-dir and --release-id must be used together")
    if args.release_id and not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", args.release_id):
        parser.error("invalid release ID")

    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"{TEMPLATE.name} needs exactly one {PLACEHOLDER} placeholder.")
    data = args.data.read_text(encoding="utf-8")
    if args.web_dir:
        build_web(template, json.loads(data), args.web_dir, args.release_id)
        return

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html_with_data(template, data), encoding="utf-8")

    size_mb = OUTPUT_HTML.stat().st_size / 1_000_000
    print(f"Wrote {OUTPUT_HTML.relative_to(PROJECT_ROOT)}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
