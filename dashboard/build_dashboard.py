#!/usr/bin/env python3
"""Build the prototype coverage dashboard as one self-contained HTML file.

Takes the template in this folder and drops the exported mart data into it, so the
result opens by double-clicking with no server, no network and no build tools.

Run the three steps in order:
    .venv/bin/python scripts/load_warehouse.py
    cd dbt && ../.venv/bin/dbt build && cd ..
    .venv/bin/python scripts/export_dashboard_data.py
    .venv/bin/python dashboard/build_dashboard.py

Writes outputs/dashboard_exports/coverage_dashboard.html.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "dashboard" / "coverage_dashboard_template.html"
DATA_JSON = PROJECT_ROOT / "outputs" / "dashboard_exports" / "dashboard_data.json"
OUTPUT_HTML = PROJECT_ROOT / "outputs" / "dashboard_exports" / "coverage_dashboard.html"

PLACEHOLDER = "__DATA__"


def main() -> None:
    for path in (TEMPLATE, DATA_JSON):
        if not path.is_file():
            raise FileNotFoundError(f"Missing required input: {path}")

    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(f"{TEMPLATE.name} has no {PLACEHOLDER} placeholder to fill.")

    data = DATA_JSON.read_text(encoding="utf-8")

    # The data goes inside a <script> block, so a literal "</script>" anywhere in a
    # post's text would end the block early and break the page. Escaping the slash
    # keeps the JSON identical to the parser while making that impossible.
    data = data.replace("</", "<\\/")

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(template.replace(PLACEHOLDER, data), encoding="utf-8")

    size_mb = OUTPUT_HTML.stat().st_size / 1_000_000
    print(f"Wrote {OUTPUT_HTML.relative_to(PROJECT_ROOT)}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
