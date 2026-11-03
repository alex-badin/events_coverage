"""Collect posts from the project's Telegram channels into a local SQLite file.

The original collector that built `news_data/ask_media_unified_messages_20260604.db` is lost.
This one replaces it for new posts only: it writes to its own file
(`news_data/telegram_collected.db` by default) and never touches the 11 GB archive, which stays
a read-only raw input. Merging the two is a later step.

The work is split in two so the logic can be tested without a Telegram account:
- this module: which channels to collect, the database layout, how one Telethon message
  becomes one row, and where each channel stopped last time;
- `scripts/collect_telegram.py`: the Telethon client, login and the download loop.

Rows use the archive's column names where one exists (`source`, `message_id`, `date`,
`original_message`, `views`, `forwards`) so a later merge is a plain column copy.
`original_message` is the post's plain text as Telegram returns it — not the JSON blob some
archive rows hold for war and military channels from 2025-02 on.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .paths import PROJECT_ROOT

MEDIA_GROUPS_YAML = PROJECT_ROOT / "configs" / "media_groups.yaml"
DEFAULT_DB = PROJECT_ROOT / "news_data" / "telegram_collected.db"
# Telethon keeps the login in this file. It is a credential: anyone holding it can read
# Telegram as the account that logged in. The folder is gitignored.
DEFAULT_SESSION = PROJECT_ROOT / ".telegram" / "events_coverage"
# The archive's last post is 2025-04-02T19:16:14+00:00; starting at the start of that day
# overlaps it by a few hours, and a merge dedupes on (source, message_id).
DEFAULT_SINCE = "2025-04-02"

SCHEMA = """
create table if not exists messages (
    source           text    not null,   -- channel username, lower case, as in media_groups.yaml
    message_id       integer not null,   -- Telegram's id of the post inside its channel
    date             text    not null,   -- UTC, ISO 8601, e.g. 2025-04-02T19:16:14+00:00
    original_message text,               -- the post's plain text; '' for a post with media only
    views            integer,
    forwards         integer,
    replies          integer,
    edit_date        text,
    grouped_id       integer,            -- shared by the posts of one album; the text sits on one
    media_type       text,               -- Telethon media class, e.g. MessageMediaPhoto
    is_forward       integer not null,   -- 1 if the post was forwarded from elsewhere
    post_author      text,
    collected_at     text    not null,
    primary key (source, message_id)
);

create table if not exists channels (
    source           text primary key,
    channel_id       integer,
    title            text,
    status           text not null,      -- in_progress | done | unavailable | error
    since            text,               -- the start date this channel was collected from
    last_message_id  integer,            -- resume point: the newest id already saved
    n_messages       integer,            -- rows in `messages` for this channel
    error            text,
    updated_at       text not null
);
"""


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def select_sources(
    path: Path = MEDIA_GROUPS_YAML,
    include_archived: bool = False,
    only: list[str] | None = None,
) -> list[str]:
    """Channel usernames to collect, in the order they appear in the config.

    By default only the sources in `groups:` (the ones in scope). `include_archived` adds the
    `archived:` block too. `only` keeps the named ones and fails on a name the config lacks,
    so a typo does not silently collect nothing.
    """
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    sources: list[str] = []
    for group in (cfg.get("groups") or {}).values():
        sources.extend(group.get("sources") or [])
    if include_archived:
        for names in (cfg.get("archived") or {}).values():
            sources.extend(names or [])
    sources = list(dict.fromkeys(s.lower() for s in sources))
    if only:
        wanted = [s.lower() for s in only]
        unknown = sorted(set(wanted) - set(sources))
        if unknown:
            raise ValueError(
                f"not in {Path(path).name} (or archived without --include-archived): {unknown}"
            )
        sources = [s for s in sources if s in wanted]
    return sources


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    return con


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def message_to_row(msg, source: str, collected_at: str) -> tuple:
    """One Telethon `Message` -> one `messages` row (column order as in SCHEMA)."""
    replies = getattr(msg, "replies", None)
    media = getattr(msg, "media", None)
    return (
        source,
        msg.id,
        _iso(msg.date),
        msg.message or "",
        getattr(msg, "views", None),
        getattr(msg, "forwards", None),
        getattr(replies, "replies", None) if replies is not None else None,
        _iso(getattr(msg, "edit_date", None)),
        getattr(msg, "grouped_id", None),
        type(media).__name__ if media is not None else None,
        1 if getattr(msg, "fwd_from", None) is not None else 0,
        getattr(msg, "post_author", None),
        collected_at,
    )


def save_rows(con: sqlite3.Connection, rows: list[tuple]) -> None:
    """Insert or refresh rows. A re-collected post gets its newer views and text."""
    con.executemany(
        "insert or replace into messages values (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )


def resume_point(con: sqlite3.Connection, source: str) -> int | None:
    """The newest message id already saved for this channel, or None if never collected.

    Read from `messages`, not from `channels`, so a crash between the two writes cannot
    skip posts.
    """
    (last,) = con.execute(
        "select max(message_id) from messages where source = ?", (source,)
    ).fetchone()
    return last


def set_channel_state(
    con: sqlite3.Connection,
    source: str,
    status: str,
    *,
    channel_id: int | None = None,
    title: str | None = None,
    since: str | None = None,
    error: str | None = None,
) -> None:
    last, n = con.execute(
        "select max(message_id), count(*) from messages where source = ?", (source,)
    ).fetchone()
    con.execute(
        """
        insert into channels (source, channel_id, title, status, since, last_message_id,
                              n_messages, error, updated_at)
        values (?,?,?,?,?,?,?,?,?)
        on conflict(source) do update set
            channel_id = coalesce(excluded.channel_id, channels.channel_id),
            title = coalesce(excluded.title, channels.title),
            status = excluded.status,
            since = coalesce(channels.since, excluded.since),
            last_message_id = excluded.last_message_id,
            n_messages = excluded.n_messages,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (source, channel_id, title, status, since, last, n, error, now_utc()),
    )
    con.commit()


def summary(con: sqlite3.Connection) -> list[tuple]:
    """(source, status, n_messages, first_date, last_date, error) for every channel tried."""
    return con.execute(
        """
        select c.source, c.status, c.n_messages, min(m.date), max(m.date), c.error
        from channels c left join messages m using (source)
        group by c.source order by c.source
        """
    ).fetchall()
