"""Offline checks for Bitcoinist article selection, embeds, and saved state."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.database as database
from modules.news.feed import (
    EMBED_COLOR,
    build_embed_dict,
    select_new_articles,
    truncate_content,
)


def _entry(year, month, day, hour=0, title="Headline", link="https://bitcoinist.com/a"):
    return {
        "title": title,
        "link": link,
        "description": "Body of the article.",
        "published_parsed": (year, month, day, hour, 0, 0),
        "media_content": [{"url": "https://cdn.example/image.jpg"}],
    }


def test_truncate_content_keeps_a_late_sentence():
    text = ("word " * 20) + "End." + (" more" * 500)
    cut = truncate_content(text, max_length=120)
    assert cut.endswith("End.")
    assert len(cut) <= 120


def test_select_new_articles_is_strictly_after_last_time_and_oldest_first():
    entries = [
        _entry(2026, 10, 30, 12, title="newer"),
        _entry(2026, 10, 29, 8, title="older"),
        _entry(2026, 10, 28, 8, title="seen"),
    ]
    last = datetime(2026, 10, 28, 8, tzinfo=timezone.utc)
    chosen = select_new_articles(entries, last)
    assert [entry["title"] for entry in chosen] == ["older", "newer"]


def test_embed_keeps_summary_format_and_drops_footer():
    article = {
        "title": "Bitcoin rises",
        "link": "https://bitcoinist.com/rises",
        "image_url": "https://cdn.example/image.jpg",
        "published": datetime(2026, 10, 30, 12, tzinfo=timezone.utc),
    }
    payload = build_embed_dict(article, "**Ringkasan:**\n> Prices moved.")
    assert payload["title"] == "Bitcoin rises"
    assert payload["url"] == "https://bitcoinist.com/rises"
    assert payload["description"].startswith("**Ringkasan:**")
    assert payload["color"] == EMBED_COLOR
    assert payload["image"]["url"] == "https://cdn.example/image.jpg"
    assert "footer" not in payload
    assert "webhook" not in str(payload).lower()


def test_news_state_is_stored_apart_from_other_features(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bot_states.db"))
    database.init_database()
    assert database.load_news_state() is None

    database.save_news_state(
        99,
        True,
        "2026-10-30T12:00:00+00:00",
        "Guild",
        "news",
        7,
    )
    loaded = database.load_news_state()
    assert loaded["channel_id"] == 99
    assert loaded["guild_id"] == 7
    assert loaded["running"] is True
    assert loaded["last_processed"] == "2026-10-30T12:00:00+00:00"
    assert database.load_channel_states() == {}
    assert database.load_forex_channel_states() == {}
    assert database.load_session_notifier_state() is None

    database.save_news_state(99, False, "2026-10-30T12:00:00+00:00", "Guild", "news", 7)
    stopped = database.load_news_state()
    assert stopped["running"] is False
    assert stopped["last_processed"] == "2026-10-30T12:00:00+00:00"
    assert stopped["channel_id"] == 99
