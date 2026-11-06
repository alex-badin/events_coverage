#!/usr/bin/env python
"""Posts of the archive for the 2,780 events before 2025-W12, cleaned exactly as new_weeks.prepare, one file per
month, so neither step holds the archive in memory. Output: data/interim/history/texts/YYYY-MM.jsonl (all fields,
sorted by date) and to_neo/YYYY-MM.txt.gz (one JSON string per line, same line order), which Neo embeds."""
import collections, gzip, json, sys, sqlite3, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "2026-11-03_new_weeks"))
import new_weeks as N  # noqa: E402
R, M = N.R, N.M
OUT = N.ROOT / "data" / "interim" / "history"
RAW, TEXTS, NEO = OUT / "raw", OUT / "texts", OUT / "to_neo"
for d in (RAW, TEXTS, NEO):
    d.mkdir(parents=True, exist_ok=True)
FIRST, LAST = (2020, 1), (2025, 3)     # windows of these events run 2020-01-03 .. 2025-03-27 (exclusive)
END = "2025-03-27"


def months():
    y, m = FIRST
    while (y, m) <= LAST:
        yield f"{y}-{m:02d}", (f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main():
    archived = M.load_archived_sources()
    db = sqlite3.connect(f"file:{N.ARCHIVE}?mode=ro", uri=True)
    index = collections.defaultdict(list)
    t0 = time.time()
    for a, b in months():
        posts = []
        for source, mid, d, text, views in db.execute(
                "SELECT source, message_id, date, original_message, views FROM unified_messages WHERE date >= ? AND date < ?",
                (a, min(b, END) if b > END else b)):
            if source not in archived and text and d < END:
                posts.append({"source": source, "message_id": str(mid), "date": d.replace(" ", "T"),
                              "raw": " ".join(R.normalize_text(text, None, max_chars=10**9).split()), "views": views})
        posts.sort(key=lambda p: p["date"])
        groups = collections.defaultdict(list)
        for p in posts:
            groups[p["source"]].append(p["raw"])
        for texts in groups.values():
            for ending, *_ in R.find_footers(texts):
                index[" ".join(ending.split()[-2:])].append(ending)
        with (RAW / f"{a}.jsonl").open("w", encoding="utf-8") as f:
            for p in posts:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(a, len(posts), f"{time.time() - t0:.0f}s", flush=True)
    for k in index:
        index[k] = sorted(set(index[k]), key=len, reverse=True)
    total = chars = 0
    for a, _ in months():
        with (RAW / f"{a}.jsonl").open(encoding="utf-8") as f, (TEXTS / f"{a}.jsonl").open("w", encoding="utf-8") as g, \
                gzip.open(NEO / f"{a}.txt.gz", "wt", encoding="utf-8") as z:
            for line in f:
                p = json.loads(line)
                p["text"] = R.clean(R.strip_footers(p.pop("raw"), index))
                g.write(json.dumps(p, ensure_ascii=False) + "\n")
                z.write(json.dumps(p["text"], ensure_ascii=False) + "\n")
                total += 1
                chars += len(p["text"])
        (RAW / f"{a}.jsonl").unlink()
    print(f"{total:,} posts, {chars:,} characters, {time.time() - t0:.0f}s")


main()
