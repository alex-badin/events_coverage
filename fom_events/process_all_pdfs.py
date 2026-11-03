"""Extract the events table from each FOM weekly report (PDF) with an OpenAI model.

Reports 2020-W02 .. 2025-W11 were extracted with Gemini (gemini-2.5-pro-exp-03-25) in 2025.
The project now calls LLMs only through the OpenAI and Anthropic APIs, so this script sends the
PDF to OpenAI's Responses API (model and prompt in config.yaml) and asks for a fixed JSON shape.

Usage, from the project root (needs OPENAI_API_KEY in .env; this is a paid call per report):
    .venv/bin/python fom_events/process_all_pdfs.py --dry-run     # which reports would run
    .venv/bin/python fom_events/process_all_pdfs.py               # every listed, not yet done
    .venv/bin/python fom_events/process_all_pdfs.py --only d10sn2025.pdf,d11sn2025.pdf \
        --output fom_events/processed_events/check_openai.json    # re-run a few into a side file

Writes, in processed_events/:
- processed_events.json   {report file name: [{"название", "цитаты", "процент"}, ...]}, the
                          shape the Gemini run produced, so build_events_table.py reads both;
- processed_events_survey_dates.json  {report file name: survey dates as printed}, to catch an
                          issue number that is not the survey week (as with d22sn2022.pdf);
- extraction_log.jsonl    one line per call: file, model, prompt hash, date, tokens.
Results are saved after every report, so a stopped run loses nothing already paid for.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
REPORTS_DIR = HERE / "downloaded_reports"
LINKS_FILE = REPORTS_DIR / "valid_pdf_links.txt"
OUT_DIR = HERE / "processed_events"

# Added to the table prompt from config.yaml: the schema below has a field for the survey dates.
SURVEY_DATES_PROMPT = (
    "\n\nКроме таблицы, выпиши в поле survey_dates даты проведения опроса так, как они "
    "напечатаны в документе (например, «29–31 июля 2022 г.»). Если дат в документе нет, "
    "оставь поле пустым. Включай в список событий все строки таблицы, в том числе "
    "«Другие события» и «Затрудняюсь ответить»."
)


class FomEvent(BaseModel):
    name: str = Field(description="название события или подсобытия")
    quotes: list[str] = Field(description="цитаты респондентов для этого события")
    percent: float | None = Field(description="процент из третьего столбца")


class FomReport(BaseModel):
    survey_dates: str
    events: list[FomEvent]


def local_pdf(url: str) -> Path | None:
    """The downloaded copy of a report, named as fom_events_download.py saves it."""
    name = url.rsplit("/", 1)[-1]
    if m := re.fullmatch(r"d(\d+)sn(\d{4})\.pdf", name):
        path = REPORTS_DIR / f"fom_report_{m.group(2)}_week{m.group(1)}.pdf"
    elif m := re.fullmatch(r"d(\d+)(\d{4})\.pdf", name):  # d222022.pdf, the one full issue
        path = REPORTS_DIR / f"fom_report_{m.group(2)}_week{m.group(1)}_{name[:-4]}.pdf"
    else:
        return None
    return path if path.exists() else None


def pdf_bytes(url: str) -> bytes:
    path = local_pdf(url)
    if path is not None:
        return path.read_bytes()
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def extract(client, pdf: bytes, filename: str, prompt: str, model: str, effort: str):
    """One report -> (FomReport, usage dict)."""
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()
    kwargs = dict(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_file", "filename": filename, "file_data": data_url},
                {"type": "input_text", "text": prompt},
            ],
        }],
        text_format=FomReport,
    )
    if effort:
        kwargs["reasoning"] = {"effort": effort}
    resp = client.responses.parse(**kwargs)
    if resp.output_parsed is None:
        raise RuntimeError(f"no parsed output (status {resp.status})")
    u = resp.usage
    return resp.output_parsed, {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens}


def as_gemini_shape(report: FomReport) -> list[dict]:
    return [
        {"название": e.name, "цитаты": e.quotes, "процент": e.percent} for e in report.events
    ]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", help="comma-separated report file names, e.g. d10sn2025.pdf")
    ap.add_argument("--output", type=Path, default=OUT_DIR / "processed_events.json")
    ap.add_argument("--force", action="store_true", help="redo reports already in --output")
    ap.add_argument("--dry-run", action="store_true", help="list what would run, call nothing")
    args = ap.parse_args()

    config = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    model = config["model"]
    effort = config.get("reasoning_effort", "")
    prompt = config["prompt_detailed"] + SURVEY_DATES_PROMPT
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:12]

    links = [x for x in LINKS_FILE.read_text().split() if x]
    if args.only:
        wanted = set(args.only.split(","))
        links = [u for u in links if u.rsplit("/", 1)[-1] in wanted]
        missing = wanted - {u.rsplit("/", 1)[-1] for u in links}
        if missing:
            sys.exit(f"not in {LINKS_FILE.name}: {sorted(missing)}")

    results = load_json(args.output)
    dates_path = args.output.with_name(args.output.stem + "_survey_dates.json")
    survey_dates = load_json(dates_path)
    todo = [u for u in links if args.force or u.rsplit("/", 1)[-1] not in results]
    print(f"{len(todo)} reports to extract with {model} (reasoning effort: {effort or 'default'})")
    if args.dry_run:
        for u in todo:
            print(" ", u.rsplit("/", 1)[-1], "local" if local_pdf(u) else "download")
        return

    load_dotenv(HERE.parent / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set in .env")
    from openai import OpenAI

    client = OpenAI(max_retries=5, timeout=300)
    log_path = OUT_DIR / "extraction_log.jsonl"
    total_in = total_out = 0
    for i, url in enumerate(todo, 1):
        filename = url.rsplit("/", 1)[-1]
        try:
            report, usage = extract(client, pdf_bytes(url), filename, prompt, model, effort)
        except Exception as exc:  # noqa: BLE001 - report and go on; a rerun retries it
            print(f"[{i}/{len(todo)}] {filename}: FAILED {type(exc).__name__}: {exc}")
            continue
        results[filename] = as_gemini_shape(report)
        survey_dates[filename] = report.survey_dates
        save_json(args.output, results)
        save_json(dates_path, survey_dates)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "file": filename, "model": model, "reasoning_effort": effort,
                "prompt_sha256_12": prompt_hash, "output": args.output.name,
                "at": datetime.now(UTC).isoformat(timespec="seconds"), **usage,
            }, ensure_ascii=False) + "\n")
        total_in += usage["input_tokens"]
        total_out += usage["output_tokens"]
        print(f"[{i}/{len(todo)}] {filename}: {len(report.events)} events, "
              f"survey {report.survey_dates!r}, tokens in {usage['input_tokens']:,} "
              f"out {usage['output_tokens']:,}", flush=True)
        time.sleep(1)
    print(f"Done. Tokens this run: input {total_in:,}, output {total_out:,}. "
          f"Saved to {args.output}")


if __name__ == "__main__":
    main()
