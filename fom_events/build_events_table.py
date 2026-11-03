"""Rebuild processed_events/events_table.csv from processed_events/processed_events.json.

The same steps as the second code cell of events_analysis.ipynb, as a script, so the table can
be rebuilt after new reports without Jupyter. It also reads the survey dates that
process_all_pdfs.py saves since the move to OpenAI, and warns when a report's survey week is
not its issue number (the trap d22sn2022.pdf fell into; those are fixed in SURVEY_WEEK_BY_FILE).

    .venv/bin/python fom_events/build_events_table.py
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
EVENTS_JSON = HERE / "processed_events" / "processed_events.json"
DATES_JSON = HERE / "processed_events" / "processed_events_survey_dates.json"
CSV_OUT = HERE / "processed_events" / "events_table.csv"

# Reports whose issue number is not the ISO week of the survey; see events_analysis.ipynb.
SURVEY_WEEK_BY_FILE = {
    "d22sn2022.pdf": (2022, 30),
    "d222022.pdf": (2022, 22),
}

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
    "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def issue_week(filename: str) -> tuple[int, int] | tuple[None, None]:
    """(year, week) of a report from its file name like 'd23sn2021.pdf'."""
    if filename in SURVEY_WEEK_BY_FILE:
        return SURVEY_WEEK_BY_FILE[filename]
    m = re.fullmatch(r"d(\d+)sn(\d{4})\.pdf", filename)
    return (int(m.group(2)), int(m.group(1))) if m else (None, None)


def survey_iso_week(text: str) -> tuple[int, int] | None:
    """ISO (year, week) of the last survey day in text like '29–31 июля 2022 г.'."""
    found = re.findall(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text.lower())
    if not found:
        return None
    day, month, year = found[-1]
    if month not in MONTHS:
        return None
    iso = date(int(year), MONTHS[month], int(day)).isocalendar()
    return iso.year, iso.week


def to_percent(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).replace("%", "").replace(",", ".").strip())
    except ValueError:
        return None


def build(data: dict, survey_dates: dict) -> tuple[pd.DataFrame, list[str]]:
    rows, warnings = [], []
    for filename, events in data.items():
        year, week = issue_week(filename)
        if year is None:
            warnings.append(f"{filename}: no year/week in the file name, skipped")
            continue
        if filename in survey_dates and filename not in SURVEY_WEEK_BY_FILE:
            survey = survey_iso_week(survey_dates[filename])
            if survey is None:
                warnings.append(f"{filename}: survey dates not readable: "
                                f"{survey_dates[filename]!r}")
            elif survey != (year, week):
                warnings.append(f"{filename}: issue {year}-W{week:02d} but survey "
                                f"{survey[0]}-W{survey[1]:02d} ({survey_dates[filename]}); "
                                "add it to SURVEY_WEEK_BY_FILE")
        if not isinstance(events, list):
            warnings.append(f"{filename}: not a list of events, skipped")
            continue
        for event in events:
            event = event if isinstance(event, dict) else {}
            rows.append({
                "date": f"{year}-{week:02d}",
                "year": year,
                "week": week,
                "event": event.get("название", ""),
                "description": event.get("цитаты", ""),
                "percentage": to_percent(event.get("процент")),
            })
    df = pd.DataFrame(rows).sort_values(
        by=["year", "week", "percentage"], ascending=[True, True, False]
    )
    return df, warnings


def main() -> None:
    data = json.loads(EVENTS_JSON.read_text(encoding="utf-8"))
    dates = json.loads(DATES_JSON.read_text(encoding="utf-8")) if DATES_JSON.exists() else {}
    df, warnings = build(data, dates)
    df.to_csv(CSV_OUT, index=False, encoding="utf-8")
    for w in warnings:
        print("WARNING", w)
    print(f"{len(df):,} rows from {df['date'].nunique()} survey weeks "
          f"({df['date'].min()} .. {df['date'].max()}) -> {CSV_OUT}")


if __name__ == "__main__":
    main()
