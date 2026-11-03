"""Collect new posts from the project's Telegram channels (Telethon, the official Telegram API).

Writes to news_data/telegram_collected.db; the 11 GB archive is never touched. Free to run,
but it needs a Telegram account:

  1. Get an api_id and api_hash at https://my.telegram.org -> "API development tools" and put
     them in .env as TELEGRAM_API_ID and TELEGRAM_API_HASH.
  2. Log in once (asks for the phone number and the code Telegram sends):
        .venv/bin/python scripts/collect_telegram.py --login
     The login is saved in .telegram/ (gitignored). Treat that folder like a password.
  3. Collect (safe to stop and start again; it resumes per channel from the newest saved post):
        .venv/bin/python scripts/collect_telegram.py
     Useful options: --channels rbc_news,meduzalive  --since 2025-04-02  --until 2025-05-01
     --include-archived  --status (print what is collected so far and exit).

Telegram slows a client down with FloodWait errors when it asks too fast. Telethon sleeps
through short waits on its own; a longer one is slept here and the channel resumes.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from events_coverage import telegram_collect as tc  # noqa: E402
from events_coverage.paths import PROJECT_ROOT  # noqa: E402

BATCH = 500  # rows written and committed together; also how far a crash can set a channel back


def parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)


def make_client(session: Path):
    from dotenv import load_dotenv
    from telethon import TelegramClient

    load_dotenv(PROJECT_ROOT / ".env")
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        sys.exit(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH are not set. Get them at https://my.telegram.org "
            "(API development tools) and add them to .env."
        )
    session.parent.mkdir(parents=True, exist_ok=True)
    # flood_sleep_threshold: Telethon sleeps by itself through FloodWaits up to this many seconds.
    return TelegramClient(str(session), int(api_id), api_hash, flood_sleep_threshold=120)


async def collect_channel(client, con, source: str, since: datetime, until: datetime) -> str:
    """Download one channel's posts from `since` (or its resume point) up to `until`."""
    from telethon import errors

    try:
        entity = await client.get_entity(source)
    except (ValueError, errors.UsernameInvalidError, errors.UsernameNotOccupiedError,
            errors.ChannelPrivateError, errors.ChannelInvalidError) as exc:
        tc.set_channel_state(con, source, "unavailable", error=f"{type(exc).__name__}: {exc}")
        return "unavailable"

    title = getattr(entity, "title", None)
    since_text = since.date().isoformat()
    while True:  # one pass normally; repeated only after a long FloodWait
        last_id = tc.resume_point(con, source)
        tc.set_channel_state(con, source, "in_progress", channel_id=entity.id, title=title,
                             since=since_text)
        # reverse=True walks from old to new. offset_date then means "posts after this date";
        # min_id skips everything already saved.
        kwargs = {"reverse": True, "offset_date": since}
        if last_id:
            kwargs["min_id"] = last_id
        rows: list[tuple] = []
        try:
            async for msg in client.iter_messages(entity, **kwargs):
                if msg.date and msg.date >= until:
                    break
                if msg.action is not None:  # service messages: pinned, title changed, ...
                    continue
                rows.append(tc.message_to_row(msg, source, tc.now_utc()))
                if len(rows) >= BATCH:
                    tc.save_rows(con, rows)
                    tc.set_channel_state(con, source, "in_progress")
                    print(f"  {source}: up to {msg.date:%Y-%m-%d}", flush=True)
                    rows = []
        except errors.FloodWaitError as exc:
            tc.save_rows(con, rows)
            tc.set_channel_state(con, source, "in_progress")
            print(f"  {source}: Telegram asks to wait {exc.seconds}s; sleeping", flush=True)
            await asyncio.sleep(exc.seconds + 5)
            continue
        except Exception as exc:  # noqa: BLE001 - record and move on to the next channel
            tc.save_rows(con, rows)
            tc.set_channel_state(con, source, "error", error=f"{type(exc).__name__}: {exc}")
            return "error"
        tc.save_rows(con, rows)
        tc.set_channel_state(con, source, "done", error=None)
        return "done"


def print_status(con) -> None:
    rows = tc.summary(con)
    if not rows:
        print("Nothing collected yet.")
        return
    print(f"{'source':24} {'status':12} {'posts':>8}  first post           last post")
    for source, status, n, first, last, error in rows:
        print(f"{source:24} {status:12} {n or 0:>8}  {(first or '')[:19]:20} {(last or '')[:19]}")
        if error:
            print(f"{'':24} {error}")
    total = sum(r[2] or 0 for r in rows)
    print(f"\n{len(rows)} channels, {total:,} posts")


async def main_async(args) -> None:
    con = tc.connect(args.db)
    if args.status:
        print_status(con)
        return

    client = make_client(args.session)
    await client.start()  # asks for phone and code only if the session is not logged in yet
    me = await client.get_me()
    print(f"Logged in to Telegram as id {me.id}")
    if args.login:
        await client.disconnect()
        return

    sources = tc.select_sources(include_archived=args.include_archived,
                                only=args.channels.split(",") if args.channels else None)
    since, until = parse_day(args.since), (parse_day(args.until) if args.until
                                           else datetime.now(UTC))
    print(f"{len(sources)} channels, posts from {since:%Y-%m-%d} to {until:%Y-%m-%d %H:%M} UTC "
          f"-> {args.db}")
    for i, source in enumerate(sources, 1):
        print(f"[{i}/{len(sources)}] {source}", flush=True)
        status = await collect_channel(client, con, source, since, until)
        n = con.execute("select count(*) from messages where source = ?", (source,)).fetchone()[0]
        print(f"  {source}: {status}, {n:,} posts in the database", flush=True)
    await client.disconnect()
    print()
    print_status(con)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--login", action="store_true", help="log in to Telegram and exit")
    ap.add_argument("--status", action="store_true", help="print what is collected and exit")
    ap.add_argument("--since", default=tc.DEFAULT_SINCE, help="first day, YYYY-MM-DD (UTC)")
    ap.add_argument("--until", default=None, help="stop before this day, YYYY-MM-DD; default now")
    ap.add_argument("--channels", default=None, help="comma-separated usernames; default all")
    ap.add_argument("--include-archived", action="store_true",
                    help="also collect the archived (out-of-scope) sources")
    ap.add_argument("--db", type=Path, default=tc.DEFAULT_DB)
    ap.add_argument("--session", type=Path, default=tc.DEFAULT_SESSION)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
