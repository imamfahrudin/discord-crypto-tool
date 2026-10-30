"""Offline checks for trading-session hours, embed content, and saved channel."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import discord
from pytz import utc

import core.database as database
from modules.session.schedule import (
    compute_sessions,
    format_time_with_offset,
    get_active_session,
    next_event_batch,
    session_changes,
    session_start_embed,
    startup_embed,
    sync_embed,
)


def test_format_time_with_offset_keeps_colon_in_zone():
    moment = datetime(2026, 1, 15, 8, 5, tzinfo=utc)
    assert format_time_with_offset(moment) == "08:05 15-01-2026 UTC+00:00"


def test_tokyo_window_is_fixed_because_japan_has_no_dst():
    winter = compute_sessions(datetime(2026, 1, 15, 12, 0, tzinfo=utc))
    summer = compute_sessions(datetime(2026, 7, 15, 12, 0, tzinfo=utc))
    assert winter["Tokyo"][:2] == (0, 9)
    assert summer["Tokyo"][:2] == (0, 9)


def test_london_and_new_york_shift_with_daylight_saving():
    winter = compute_sessions(datetime(2026, 1, 15, 12, 0, tzinfo=utc))
    summer = compute_sessions(datetime(2026, 7, 15, 12, 0, tzinfo=utc))
    assert winter["London"][:2] == (8, 17)
    assert summer["London"][:2] == (7, 16)
    assert winter["New York"][:2] == (13, 22)
    assert summer["New York"][:2] == (12, 21)
    changes = session_changes(winter, summer)
    assert any(line.startswith("London:") for line in changes)
    assert any(line.startswith("New York:") for line in changes)
    assert session_changes(winter, winter) == []


def test_active_session_handles_overnight_window():
    sessions = {
        "Sydney": (22, 7, "Australia/Sydney", 1),
        "Tokyo": (0, 9, "Asia/Tokyo", 2),
    }
    assert get_active_session(sessions, 23) == "Sydney"
    assert get_active_session(sessions, 3) == "Sydney"
    assert get_active_session(sessions, 8) == "Tokyo"


def test_next_event_is_the_sooner_of_sync_or_session_open():
    sessions = compute_sessions(datetime(2026, 1, 15, 5, 30, tzinfo=utc))
    when, batch = next_event_batch(sessions, datetime(2026, 1, 15, 5, 30, tzinfo=utc))
    assert when == datetime(2026, 1, 15, 6, 0, tzinfo=utc)
    assert batch[0][0] == "sync"

    later, later_batch = next_event_batch(sessions, datetime(2026, 1, 15, 6, 0, tzinfo=utc))
    assert later > datetime(2026, 1, 15, 6, 0, tzinfo=utc)
    assert all(item[1] == later for item in later_batch)


def test_embeds_have_original_titles_and_no_footer_or_role():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=utc)
    sessions = compute_sessions(now)
    for payload in (
        startup_embed(sessions, now),
        session_start_embed("London", sessions, now),
        sync_embed(["London: 07:00-16:00 UTC"], now),
    ):
        assert "footer" not in payload
        assert "content" not in payload
        blob = str(payload)
        assert "<@&" not in blob
        assert "webhook" not in blob.lower()

    assert startup_embed(sessions, now)["title"] == "✅ Trading Session Notifier Started"
    assert session_start_embed("London", sessions, now)["title"] == "London Trading Session Started"
    assert sync_embed(["London: 07:00-16:00 UTC"], now)["title"] == "🔄 Trading Sessions Updated"

    embed = discord.Embed.from_dict(startup_embed(sessions, now))
    assert embed.title == "✅ Trading Session Notifier Started"
    assert not embed.footer.text


def test_session_channel_is_stored_apart_from_vwap_and_forex(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bot_states.db"))
    database.init_database()
    assert database.load_session_notifier_state() is None

    database.save_session_notifier_state(42, True, "Guild", "alerts", 7)
    loaded = database.load_session_notifier_state()
    assert loaded["channel_id"] == 42
    assert loaded["guild_id"] == 7
    assert loaded["running"] is True
    assert database.load_forex_channel_states() == {}
    assert database.load_channel_states() == {}

    database.remove_session_notifier_state()
    assert database.load_session_notifier_state() is None
