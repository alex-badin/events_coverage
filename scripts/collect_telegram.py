"""Collect the posts the news archive lacks (after 2025-04-02) from public Telegram channel previews.

Reads t.me/s/<channel> pages, newest first, for the 56 in-scope channels of configs/media_groups.yaml
and stops per channel at the newest post the archive already has (news_data/ask_media_unified_*.db).
The SQLite database contains normalized post text and compressed source HTML. Progress is committed
after every page, so rerunning the same command resumes incomplete channels. No Telegram account,
no API keys and no media binaries are used; no new dependencies (PyYAML is already in the venv).
Adapted from misinfo_tracking_moldova/collectors/telegram/collect_telegram_history.py.

Not in the previews: forward counts, and the Telegram JSON form some military channels have in
original_message. Views come as display text ("1.2K").
"""

import argparse
import datetime as dt
import html
from html.parser import HTMLParser
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs" / "media_groups.yaml"
ARCHIVE = ROOT / "news_data" / "ask_media_unified_messages_20260604.db"
ARCHIVE_END = "2025-04-02T19:16:14+00:00"   # the newest post in the archive
POST_RE = re.compile(r'data-post="([^"/]+)/(\d+)"')
DATE_RE = re.compile(r'<time datetime="([^"]+)"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
VIEWS_RE = re.compile(r'<span class="tgme_widget_message_views">([^<]+)</span>')
SERVICE_RE = re.compile(
    r"^The owner of this channel has been inactive for the last \d+ months?\b|"
    r"^Channel created$|^Channel name was changed to ", re.I
)
MEDIA_RE = re.compile(
    r"tgme_widget_message_(?:photo|video|document|voice|audio|poll|sticker)|"
    r"js-message_photo|js-message_video"
)
USER_AGENT = "Mozilla/5.0 (compatible; events-coverage-archive/1.0)"


class MessageText(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag in {"br", "p", "blockquote", "div"}:
                self.parts.append(" ")
            if tag not in self.VOID_TAGS:
                self.depth += 1
        elif tag == "div" and "tgme_widget_message_text" in dict(attrs).get("class", "").split():
            self.depth = 1

    def handle_startendtag(self, tag, attrs):
        if self.depth and tag == "br":
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def text(self):
        return " ".join("".join(self.parts).split())


def parse_page(body):
    matches = list(POST_RE.finditer(body))
    posts = []
    undated = 0
    for index, match in enumerate(matches):
        section = body[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(body)]
        date_match = DATE_RE.search(section)
        if not date_match:
            undated += 1
            continue
        try:
            published = dt.datetime.fromisoformat(date_match.group(1)).astimezone(dt.timezone.utc)
        except ValueError:
            undated += 1
            continue
        parser = MessageText()
        parser.feed(section)
        text = parser.text()
        if SERVICE_RE.search(text):
            kind = "service"
        elif text:
            kind = "text"
        elif "message_media_not_supported" in section or "text_not_supported_wrap" in section:
            kind = "unreadable"
        elif MEDIA_RE.search(section):
            kind = "media_only"
        else:
            kind = "empty"
        views_match = VIEWS_RE.search(section)
        posts.append({
            "message_id": int(match.group(2)),
            "actual_handle": match.group(1),
            "published_utc": published.isoformat(),
            "text": text,
            "record_type": kind,
            "has_media": bool(MEDIA_RE.search(section)),
            "views_text": html.unescape(views_match.group(1)) if views_match else None,
            "url": f"https://t.me/{match.group(1)}/{match.group(2)}",
        })
    return posts, undated


def connect(path):
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize(conn, rows, start, end, source_starts=None):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS collection (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY, handle TEXT NOT NULL, name TEXT NOT NULL,
            source_group TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            next_before INTEGER, pages_fetched INTEGER NOT NULL DEFAULT 0,
            posts_saved INTEGER NOT NULL DEFAULT 0, oldest_seen_utc TEXT,
            newest_seen_utc TEXT, last_http_status INTEGER, page_title TEXT,
            error TEXT, updated_utc TEXT
        );
        CREATE TABLE IF NOT EXISTS pages (
            page_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL,
            request_url TEXT NOT NULL UNIQUE, fetched_utc TEXT NOT NULL,
            http_status INTEGER NOT NULL, first_id INTEGER, last_id INTEGER,
            post_elements INTEGER NOT NULL, undated_elements INTEGER NOT NULL,
            html_zlib BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts (
            source_id TEXT NOT NULL, message_id INTEGER NOT NULL,
            actual_handle TEXT NOT NULL, url TEXT NOT NULL,
            published_utc TEXT NOT NULL, text TEXT NOT NULL,
            record_type TEXT NOT NULL, has_media INTEGER NOT NULL,
            views_text TEXT, page_id INTEGER NOT NULL,
            PRIMARY KEY (source_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS posts_published_idx ON posts(published_utc);
        CREATE INDEX IF NOT EXISTS posts_record_type_idx ON posts(record_type);
    """)
    existing = dict(conn.execute("SELECT key, value FROM collection"))
    wanted = {"start_utc": start.isoformat(), "end_utc": end.isoformat(),
              "registry_path": REGISTRY.relative_to(ROOT).as_posix(), "archive": ARCHIVE.name}
    if source_starts:
        wanted["source_starts"] = json.dumps({k: v.isoformat() for k, v in sorted(source_starts.items())})
    for key, value in wanted.items():
        if key in existing and existing[key] != value:
            raise ValueError(f"Existing database has different {key}: {existing[key]}")
        conn.execute("INSERT OR IGNORE INTO collection VALUES (?, ?)", (key, value))
    for row in rows:
        conn.execute("""INSERT OR IGNORE INTO sources
            (source_id, handle, name, source_group) VALUES (?, ?, ?, ?)""",
            (row["source_id"], row["handle"], row["name"], row["group"]))
    conn.commit()


class RateControl:
    def __init__(self):
        self.lock = threading.Lock()
        self.pause_until = 0.0
        self.flood_count = 0

    def wait(self):
        while True:
            with self.lock:
                delay = self.pause_until - time.monotonic()
            if delay <= 0:
                return
            time.sleep(min(delay, 5))

    def flood(self, retry_after):
        with self.lock:
            self.flood_count += 1
            delay = max(retry_after, min(30 * 2 ** min(self.flood_count - 1, 4), 300))
            self.pause_until = max(self.pause_until, time.monotonic() + delay)
            return delay


def fetch(url, limiter):
    for attempt in range(5):
        limiter.wait()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    retry_after = int(exc.headers.get("Retry-After", "30"))
                except ValueError:
                    retry_after = 30
                print(f"HTTP 429; pausing all workers for {limiter.flood(retry_after)}s", flush=True)
                continue
            if exc.code not in {500, 502, 503, 504} or attempt == 4:
                return exc.code, exc.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 4:
                raise
        time.sleep(min(3 * 2 ** attempt, 30))
    raise RuntimeError(f"Too many HTTP 429 responses for {url}")


def collect_one(db_path, source_id, start, end, limiter, max_pages):
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
        if row["state"] in {"complete", "no_in_range", "no_public_history"}:
            return source_id, row["state"], row["pages_fetched"], row["posts_saved"]
        handle = row["handle"].lstrip("@")
        base_url = "https://t.me/s/" + urllib.parse.quote(handle)
        pages_this_run = 0
        while True:
            if max_pages is not None and pages_this_run >= max_pages:
                return source_id, "sampled", row["pages_fetched"], row["posts_saved"]
            before = row["next_before"]
            url = base_url + (f"?before={before}" if before else "")
            try:
                status, body = fetch(url, limiter)
            except Exception as exc:
                conn.execute("UPDATE sources SET state='failed', error=?, updated_utc=? WHERE source_id=?",
                             (repr(exc), dt.datetime.now(dt.timezone.utc).isoformat(), source_id))
                conn.commit()
                return source_id, "failed", row["pages_fetched"], row["posts_saved"]
            fetched = dt.datetime.now(dt.timezone.utc).isoformat()
            title_match = TITLE_RE.search(body)
            title = html.unescape(title_match.group(1)).strip() if title_match else None
            posts, undated = parse_page(body) if status == 200 else ([], 0)
            ids = [int(match.group(2)) for match in POST_RE.finditer(body)] if status == 200 else []
            dated = [post["published_utc"] for post in posts]
            new_oldest = min(dated) if dated else None
            new_newest = max(dated) if dated else None
            old_oldest = row["oldest_seen_utc"]
            old_newest = row["newest_seen_utc"]
            oldest = min(filter(None, (old_oldest, new_oldest)), default=None)
            newest = max(filter(None, (old_newest, new_newest)), default=None)
            saved = [post for post in posts if start.isoformat() <= post["published_utc"] <= end.isoformat()]
            if status != 200:
                # a closed or missing channel answers 200 without post elements; any other status (403, 429, 5xx)
                # says nothing about the channel, so it must not pass for "no public history"
                state = "failed"
                error = f"HTTP {status}"
            elif not ids:
                state = "no_public_history" if before is None else "complete"
                error = "No public post elements" if before is None else None
            elif before is not None and min(ids) >= before:
                state = "failed"
                error = f"Pagination did not move before {before}"
            elif new_oldest and new_oldest < start.isoformat():
                state = "complete" if row["pages_fetched"] or saved else "no_in_range"
                error = None
            else:
                state = "running"
                error = None
            with conn:
                cursor = conn.execute("""INSERT INTO pages
                    (source_id, request_url, fetched_utc, http_status, first_id, last_id,
                     post_elements, undated_elements, html_zlib)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(request_url) DO UPDATE SET
                        fetched_utc=excluded.fetched_utc, http_status=excluded.http_status,
                        first_id=excluded.first_id, last_id=excluded.last_id,
                        post_elements=excluded.post_elements,
                        undated_elements=excluded.undated_elements,
                        html_zlib=excluded.html_zlib
                    RETURNING page_id""",
                    (source_id, url, fetched, status, min(ids) if ids else None,
                     max(ids) if ids else None, len(ids), undated,
                     zlib.compress(body.encode("utf-8"), level=3)))
                page_id = cursor.fetchone()[0]
                for post in saved:
                    conn.execute("""INSERT OR IGNORE INTO posts
                        (source_id, message_id, actual_handle, url, published_utc, text,
                         record_type, has_media, views_text, page_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (source_id, post["message_id"], post["actual_handle"], post["url"],
                         post["published_utc"], post["text"], post["record_type"],
                         int(post["has_media"]), post["views_text"], page_id))
                conn.execute("""UPDATE sources SET state=?, next_before=?, pages_fetched=pages_fetched+1,
                    posts_saved=(SELECT COUNT(*) FROM posts WHERE source_id=?),
                    oldest_seen_utc=?, newest_seen_utc=?, last_http_status=?, page_title=?,
                    error=?, updated_utc=? WHERE source_id=?""",
                    (state, min(ids) if ids else before, source_id, oldest, newest,
                     status, title, error, fetched, source_id))
            pages_this_run += 1
            row = conn.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
            if pages_this_run % 50 == 0:
                print(f"{source_id} {handle}: {row['pages_fetched']} pages, {row['posts_saved']} posts, oldest {oldest}", flush=True)
            if state != "running":
                return source_id, state, row["pages_fetched"], row["posts_saved"]
            time.sleep(0.2)
    finally:
        conn.close()


def registry():
    """In-scope channels of configs/media_groups.yaml; the source name is the Telegram handle."""
    groups = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["groups"]
    return [{"source_id": s, "handle": s, "name": s, "group": g} for g, v in groups.items() for s in v["sources"]]


def archive_ends(sources):
    """Newest post per channel in the archive (read-only); channels with nothing since 2025 are left out."""
    conn = sqlite3.connect(f"file:{ARCHIVE}?mode=ro", uri=True)
    q = (f"SELECT source, MAX(date) FROM unified_messages WHERE date >= '2025-01-01' "
         f"AND source IN ({','.join('?' * len(sources))}) GROUP BY source")
    ends = {s: d.replace(" ", "T") for s, d in conn.execute(q, sources)}
    conn.close()
    return ends


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="SQLite output path")
    parser.add_argument("--source-id", action="append", help="Only collect these source IDs")
    parser.add_argument("--max-pages-per-source", type=int, help="For a bounded trial")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--since", default=ARCHIVE_END, help="Start (ISO time, UTC) for channels the archive has "
                        "nothing on since 2025; every other channel starts at its own newest archived post")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    db_path = args.db or ROOT / "news_data" / f"telegram_previews_{now.date().isoformat()}.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    rows = registry()
    if args.source_id:
        wanted = set(args.source_id)
        rows = [row for row in rows if row["source_id"] in wanted]
        if len(rows) != len(wanted):
            raise ValueError(f"Unknown source IDs: {wanted - {row['source_id'] for row in rows}}")
    conn = connect(db_path)
    existing = dict(conn.execute("SELECT key, value FROM collection")) if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='collection'").fetchone() else {}
    end = dt.datetime.fromisoformat(existing["end_utc"]) if "end_utc" in existing else now
    if "start_utc" in existing:
        start = dt.datetime.fromisoformat(existing["start_utc"])
    else:
        start = dt.datetime.fromisoformat(args.since).astimezone(dt.timezone.utc)
    if "source_starts" in existing:
        source_starts = json.loads(existing["source_starts"])
    else:
        source_starts = archive_ends([row["source_id"] for row in rows])
    source_starts = {k: dt.datetime.fromisoformat(v).astimezone(dt.timezone.utc) for k, v in source_starts.items()}
    default_start = start
    if "start_utc" not in existing and source_starts:
        start = min(start, *source_starts.values())  # the database's period covers every channel's own start
    initialize(conn, rows, start, end, source_starts)
    conn.close()
    print(json.dumps({"database": str(db_path), "sources": len(rows),
                      "start_utc": start.isoformat(), "end_utc": end.isoformat()}, ensure_ascii=False), flush=True)
    limiter = RateControl()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(collect_one, db_path, row["source_id"], source_starts.get(row["source_id"], default_start), end,
                               limiter, args.max_pages_per_source): row for row in rows}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                source_id, state, pages, posts = future.result()
                print(f"[{index}/{len(rows)}] {source_id}: {state}; {pages} pages, {posts} records", flush=True)
            except Exception as exc:
                source_id = futures[future]["source_id"]
                print(f"[{index}/{len(rows)}] {source_id}: ERROR {exc!r}", flush=True)
    conn = connect(db_path)
    summary = {
        "database": str(db_path),
        "period_utc": [start.isoformat(), end.isoformat()],
        "source_states": dict(conn.execute("SELECT state, COUNT(*) FROM sources GROUP BY state")),
        "pages": conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
        "records": conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0],
        "record_types": dict(conn.execute("SELECT record_type, COUNT(*) FROM posts GROUP BY record_type")),
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    conn.close()


if __name__ == "__main__":
    main()
