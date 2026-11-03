"""Extract the weekly event list from FOM report PDFs with Codex (subscription), into processed_events.json.

Replaces the Gemini step of process_all_pdfs.py for reports that processed_events.json does not have
yet. Each PDF is turned into its text boxes with position and bold (pdftohtml -xml, poppler): FOM marks
sub-events in bold, which plain pdftotext loses. Codex gets the prompt_detailed instructions of
config.yaml plus those boxes and answers in the same JSON shape Gemini produced.

    python extract_events_codex.py prompts [file.pdf ...]   # write codex_extraction/prompts/<key>.txt
    zsh ../exploration/2026-10-17_jev_selection/codex_answer.sh codex_extraction   # answer them (Codex)
    python extract_events_codex.py check                    # survey dates vs ISO week, answers vs old ones
    python extract_events_codex.py merge                    # add new answers to processed_events.json

Then rerun events_analysis.ipynb (first cells) to rebuild events_table.csv.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PDFS = HERE / "downloaded_reports"
EVENTS = HERE / "processed_events" / "processed_events.json"
WORK = HERE / "codex_extraction"
MONTHS = {m: i for i, m in enumerate(["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                                      "сентября", "октября", "ноября", "декабря"], 1)}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["events"], "properties": {"events": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["название", "цитаты", "процент"],
                               "properties": {"название": {"type": "string"},
                                              "цитаты": {"type": "array", "items": {"type": "string"}},
                                              "процент": {"type": "number"}}}}}}
HOW_TO_READ = """

Ниже — не сам PDF, а его текстовые блоки по порядку: «top left: текст», где top и left — положение блока на
странице в пикселях (у колонок таблицы свой left), а <b>…</b> — жирный шрифт. Названия событий и
подсобытий набраны жирным; проценты — жирные числа справа (у подсобытия своя колонка процентов левее
колонки основного события). Строку «Затрудняюсь ответить, нет ответа» тоже включи, как событие.
Каждую цитату в «цитаты» давай отдельной строкой в кавычках-ёлочках, как в документе.
Ответ — JSON {"events": [...]}, элементы в порядке таблицы.

Текстовые блоки:
"""


def key(pdf: Path) -> str | None:
    """fom_report_2025_week11.pdf -> d11sn2025.pdf, the name processed_events.json uses."""
    m = re.fullmatch(r"fom_report_(\d{4})_week(\d+)\.pdf", pdf.name)
    return f"d{m.group(2)}sn{m.group(1)}.pdf" if m else None


def boxes(pdf: Path) -> str:
    xml = subprocess.run(["pdftohtml", "-xml", "-i", "-stdout", "-q", str(pdf)], capture_output=True,
                         text=True, check=True).stdout
    lines = []
    for page, body in re.findall(r'<page number="(\d+)"(.*?)</page>', xml, re.S):
        for top, left, text in re.findall(r'<text top="(\d+)" left="(\d+)"[^>]*>(.*?)</text>', body, re.S):
            text = re.sub(r"</?(?!b>)[a-z][^>]*>", "", text).replace("&quot;", '"').replace("&amp;", "&")
            if text.strip():
                lines.append(f"p{page} {top} {left}: {text.strip()}")
    return "\n".join(lines)


def survey_week(pdf: Path) -> tuple[int, int] | None:
    """ISO (year, week) of the survey's last day, read from 'Опрос «ФОМнибус» 14–16 марта.'"""
    text = subprocess.run(["pdftotext", "-l", "2", str(pdf), "-"], capture_output=True, text=True).stdout
    m = re.search(r"Опрос[^\n]*?(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?\s*(?:г\.)?\s*\.", text)
    if not m or m.group(2) not in MONTHS:
        return None
    year = int(m.group(3) or re.search(r"(\d{4})", pdf.name).group(1))
    return dt.date(year, MONTHS[m.group(2)], int(m.group(1))).isocalendar()[:2]


def prompts(names: list[str]) -> None:
    done = json.loads(EVENTS.read_text(encoding="utf-8"))
    instructions = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))["prompt_detailed"]
    (WORK / "prompts").mkdir(parents=True, exist_ok=True)
    (WORK / "schema.json").write_text(json.dumps(SCHEMA, ensure_ascii=False, indent=2))
    pdfs = [PDFS / n for n in names] if names else sorted(PDFS.glob("fom_report_*.pdf"))
    for pdf in pdfs:
        k = key(pdf)
        if k is None or (k in done and not names):
            continue
        (WORK / "prompts" / f"{k[:-4]}.txt").write_text(instructions + HOW_TO_READ + boxes(pdf), encoding="utf-8")
        print(f"{pdf.name} -> {k}")


def answers() -> dict[str, list]:
    return {f"{p.stem}.pdf": json.loads(p.read_text())["events"] for p in sorted((WORK / "out").glob("*.json"))}


def check() -> None:
    """Survey week printed in each report vs the week in its address; for reports Gemini already did,
    how many event names Codex and Gemini share (a test of the extraction, not used in the merge)."""
    done = json.loads(EVENTS.read_text(encoding="utf-8"))
    for k, events in answers().items():
        m = re.fullmatch(r"d(\d+)sn(\d{4})\.pdf", k)
        pdf = PDFS / f"fom_report_{m.group(2)}_week{m.group(1)}.pdf"
        sw = survey_week(pdf)
        flag = "" if sw == (int(m.group(2)), int(m.group(1))) else f"  <-- survey week {sw}"
        line = f"{k}: {len(events)} events, sum {sum(e['процент'] for e in events):.0f}%{flag}"
        if k in done:
            old = {e["название"].strip() for e in done[k]}
            new = {e["название"].strip() for e in events}
            line += f"; vs Gemini: {len(old & new)} shared names, {len(old - new)} only Gemini, {len(new - old)} only Codex"
        print(line)


def merge() -> None:
    done = json.loads(EVENTS.read_text(encoding="utf-8"))
    new = {k: v for k, v in answers().items() if k not in done}
    done.update(new)
    EVENTS.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"added {len(new)} reports: {', '.join(new)}")


if __name__ == "__main__":
    {"prompts": lambda: prompts(sys.argv[2:]), "check": check, "merge": merge}[sys.argv[1]]()
