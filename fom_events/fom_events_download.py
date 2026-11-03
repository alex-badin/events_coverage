"""Download FOM's weekly "events of the week" reports (PDF) and list the ones that exist.

FOM publishes each report at https://media.fom.ru/fom-bd/d{N}sn{YYYY}.pdf, where N is the issue
number. N is the ISO week of the survey for every report but one: d22sn2022.pdf holds 2022-W30
(see events_analysis.ipynb). The real 2022-W22 list is at d222022.pdf, outside this pattern.

Usage, from the project root:
    .venv/bin/python fom_events/fom_events_download.py                 # weeks after the last known
    .venv/bin/python fom_events/fom_events_download.py --since 2025-12  # from 2025-W12 on

Saved as downloaded_reports/fom_report_{YYYY}_week{N}.pdf. valid_pdf_links.txt is only ever
added to: links already in it (the hand-added d222022.pdf among them) stay, in their order.
"""

import argparse
import logging
import re
import time
from datetime import date
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SAVE_DIR = HERE / "downloaded_reports"
LINKS_FILE = SAVE_DIR / "valid_pdf_links.txt"
BASE_URL = "https://media.fom.ru/fom-bd/d{week}sn{year}.pdf"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def download_pdf(url: str, save_path: Path) -> bool:
    """Save the PDF at `url`; False if it does not exist or is not a PDF."""
    try:
        response = requests.get(url, timeout=30)
    except requests.exceptions.RequestException as exc:
        logging.error(f"Error downloading {url}: {exc}")
        return False
    if response.status_code == 404:
        return False
    if response.status_code != 200:
        logging.error(f"{url}: HTTP {response.status_code}")
        return False
    if not response.content.startswith(b"%PDF"):
        logging.warning(f"{url} is not a PDF. Skipping.")
        return False
    save_path.write_bytes(response.content)
    logging.info(f"Downloaded: {url}")
    return True


def last_known_week(links: list[str]) -> tuple[int, int]:
    """(year, issue) of the newest dNsnYYYY link already listed; (2020, 0) if none."""
    found = [
        (int(m.group(2)), int(m.group(1)))
        for link in links
        if (m := re.search(r"/d(\d+)sn(\d{4})\.pdf$", link))
    ]
    return max(found, default=(2020, 0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--since", help="first year-issue to try, YYYY-NN; default: after the last "
                    "link in valid_pdf_links.txt")
    args = ap.parse_args()

    SAVE_DIR.mkdir(exist_ok=True)
    links = LINKS_FILE.read_text().split() if LINKS_FILE.exists() else []
    if args.since:
        start_year, start_week = (int(x) for x in args.since.split("-"))
    else:
        start_year, start_week = last_known_week(links)
        start_week += 1
    today = date.today()
    this_year, this_week = today.isocalendar().year, today.isocalendar().week
    logging.info(f"Trying issues from {start_year}-{start_week:02d} to {this_year}-{this_week:02d}")

    new_links, missing = [], []
    for year in range(start_year, this_year + 1):
        first = start_week if year == start_year else 1
        last = this_week if year == this_year else 53
        for week in range(first, last + 1):
            # FOM wrote early-year issue numbers both as "7" and "07"; try both.
            for week_str in dict.fromkeys([f"{week:02d}", f"{week}"]):
                url = BASE_URL.format(week=week_str, year=year)
                save_path = SAVE_DIR / f"fom_report_{year}_week{week_str}.pdf"
                if url in links or save_path.exists() or download_pdf(url, save_path):
                    if url not in links:
                        new_links.append(url)
                    break
                time.sleep(1)  # be gentle with FOM's server
            else:
                missing.append(f"{year}-{week:02d}")

    existing = LINKS_FILE.read_text() if LINKS_FILE.exists() else ""
    with LINKS_FILE.open("a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        for link in new_links:
            f.write(f"{link}\n")
    logging.info(f"Added {len(new_links)} links to {LINKS_FILE}")
    if missing:
        logging.info(f"No report for {len(missing)} issue numbers: {', '.join(missing)}")


if __name__ == "__main__":
    main()
