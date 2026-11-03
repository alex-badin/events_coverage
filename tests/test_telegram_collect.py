"""The Telegram collector's offline logic: channel list, row mapping, resume point."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from events_coverage import telegram_collect as tc

CONFIG = """
groups:
  a:
    sources: [Rbc_News, meduzalive]
  b:
    sources: [rybar, rbc_news]
archived:
  reason_regional: [perm36]
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "media_groups.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_select_sources_in_scope_only_lowercased_and_deduped(config):
    assert tc.select_sources(config) == ["rbc_news", "meduzalive", "rybar"]


def test_select_sources_with_archived(config):
    assert tc.select_sources(config, include_archived=True)[-1] == "perm36"


def test_select_sources_only_rejects_unknown_names(config):
    assert tc.select_sources(config, only=["RYBAR"]) == ["rybar"]
    with pytest.raises(ValueError, match="perm36"):
        tc.select_sources(config, only=["perm36"])


class MessageMediaPhoto:  # stands in for Telethon's media class; only the name is stored
    pass


def fake_message(msg_id, text="текст", **extra):
    base = dict(
        id=msg_id, date=datetime(2025, 4, 3, 10, 0, tzinfo=UTC), message=text, views=100,
        forwards=2, replies=None, edit_date=None, grouped_id=None, media=None, fwd_from=None,
        post_author=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def test_message_to_row_maps_fields():
    msg = fake_message(7, text=None, media=MessageMediaPhoto(),
                       replies=SimpleNamespace(replies=4), fwd_from=object())
    row = tc.message_to_row(msg, "rybar", "2026-11-03T00:00:00+00:00")
    assert row[:7] == ("rybar", 7, "2025-04-03T10:00:00+00:00", "", 100, 2, 4)
    assert row[9] == "MessageMediaPhoto"
    assert row[10] == 1


def test_resume_point_and_channel_state(tmp_path):
    con = tc.connect(tmp_path / "t.db")
    assert tc.resume_point(con, "rybar") is None
    rows = [tc.message_to_row(fake_message(i), "rybar", "x") for i in (5, 9, 7)]
    tc.save_rows(con, rows)
    tc.save_rows(con, [tc.message_to_row(fake_message(9, views=500), "rybar", "y")])
    assert tc.resume_point(con, "rybar") == 9
    tc.set_channel_state(con, "rybar", "in_progress", since="2025-04-02", title="Рыбарь")
    tc.set_channel_state(con, "rybar", "done", since="2026-01-01")
    source, status, n, first, last, error = tc.summary(con)[0]
    assert (source, status, n, error) == ("rybar", "done", 3, None)
    # the first start date is kept; a re-collected post is refreshed, not duplicated
    assert con.execute("select since, title from channels").fetchone() == ("2025-04-02", "Рыбарь")
    assert con.execute("select views from messages where message_id = 9").fetchone() == (500,)
