"""
Forex Factory data fetcher — pure data layer, no Discord dependencies.
Fetches and parses the weekly economic calendar XML feed from Forex Factory.
"""

from __future__ import annotations

import time
import calendar
import logging
import traceback
from datetime import datetime, timezone

import requests
import xml.etree.ElementTree as ET
import pytz

from config import (
    FOREX_MAX_UPCOMING,
    FOREX_MIN_IMPACT,
    FOREX_CURRENCIES,
    FOREX_TIMEZONE,
    FOREX_MAX_RETRIES,
    FOREX_INITIAL_SLEEP_SECONDS,
    FOREX_REQUEST_TIMEOUT,
    FOREX_MAX_EVENT_TITLE_LENGTH,
    FOREX_USER_AGENT,
)

logger = logging.getLogger("crypto_tool.forex.fetcher")

# Forex Factory weekly calendar XML feed (no API key required)
XML_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"


def fetch_all_news() -> dict:
    """
    Fetch and parse economic calendar events from the Forex Factory XML feed.

    Returns:
        dict with keys:
            'today'    – list of today's event dicts
            'upcoming' – list of future event dicts (capped at FOREX_MAX_UPCOMING)
            'today_str'– date string (YYYY-MM-DD) for the embed title
    """
    tz_obj = pytz.timezone(FOREX_TIMEZONE)

    logger.info(f"⏳ Sleeping {FOREX_INITIAL_SLEEP_SECONDS}s before fetch…")
    time.sleep(FOREX_INITIAL_SLEEP_SECONDS)

    headers = {"User-Agent": FOREX_USER_AGENT}

    for attempt in range(FOREX_MAX_RETRIES):
        try:
            logger.info(f"🚀 XML fetch (attempt {attempt + 1}/{FOREX_MAX_RETRIES})…")
            resp = requests.get(XML_URL, headers=headers, timeout=FOREX_REQUEST_TIMEOUT)
            logger.info(f"HTTP status: {resp.status_code}")

            if resp.status_code == 429:
                wait = 10 * (2 ** attempt)
                logger.warning(f"Rate-limited — sleeping {wait}s…")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                logger.error(f"Non-200 response: {resp.status_code}")
                return {"today": [], "upcoming": [], "today_str": ""}

            root = ET.fromstring(resp.content)
            all_events = root.findall("event")
            logger.info(f"Parsed {len(all_events)} raw events.")

            now_local = datetime.now(tz_obj)
            today_date = now_local.date()
            today_str = now_local.strftime("%Y-%m-%d")

            events: dict = {"today": [], "upcoming": []}
            skipped_past = skipped_fuzzy = skipped_filter = 0

            for i, elem in enumerate(all_events):
                try:
                    date_elem = elem.find("date")
                    if date_elem is None or not (date_elem.text or "").strip():
                        continue
                    date_str = date_elem.text.strip()

                    time_elem = elem.find("time")
                    time_str = (time_elem.text or "").strip() if time_elem is not None else ""

                    # Skip TBA / Tentative / All Day events
                    if not time_str or time_str in ("TBA", "Tentative") or "All Day" in time_str:
                        skipped_fuzzy += 1
                        continue

                    # Try multiple time formats
                    event_time = None
                    for fmt in ("%I:%M%p", "%H:%M", "%I:%M %p"):
                        try:
                            event_time = datetime.strptime(time_str, fmt)
                            break
                        except ValueError:
                            continue

                    if event_time is None:
                        skipped_fuzzy += 1
                        continue

                    event_date_full = datetime.strptime(date_str, "%m-%d-%Y")
                    event_utc = event_date_full.replace(
                        hour=event_time.hour,
                        minute=event_time.minute,
                        second=0,
                        microsecond=0,
                        tzinfo=timezone.utc,
                    )
                    event_local = event_utc.astimezone(tz_obj)
                    event_date_local = event_local.date()

                    if event_date_local < today_date:
                        skipped_past += 1
                        continue

                    title_elem = elem.find("title")
                    title = (title_elem.text or "Unknown").strip() if title_elem is not None else "Unknown"

                    country_elem = elem.find("country")
                    currency = (country_elem.text or "USD").strip().upper() if country_elem is not None else "USD"

                    impact_elem = elem.find("impact")
                    impact = (impact_elem.text or "medium").strip().lower() if impact_elem is not None else "medium"

                    # Impact filter
                    if FOREX_MIN_IMPACT != "all" and impact != FOREX_MIN_IMPACT:
                        skipped_filter += 1
                        continue

                    # Currency filter
                    if FOREX_CURRENCIES and currency not in FOREX_CURRENCIES:
                        skipped_filter += 1
                        continue

                    # Build event URL
                    url_elem = elem.find("url")
                    link = (url_elem.text or "").strip() if url_elem is not None else ""
                    if not link:
                        parts_date = date_str.split("-")
                        month_abbr = calendar.month_abbr[int(parts_date[0])].lower()
                        link = f"https://www.forexfactory.com/calendar.php?day={month_abbr}{parts_date[1]}.{parts_date[2]}"

                    tz_abbrev = event_local.strftime("%Z")
                    event_data = {
                        "time_utc": event_utc.strftime("%H:%M UTC"),
                        "time_local": event_local.strftime(f"%H:%M {tz_abbrev}"),
                        "currency": currency,
                        "event": title,
                        "impact": impact,
                        "date_str": event_local.strftime("%d %B %Y"),
                        "sort_date": event_date_local,
                        "link": link,
                    }

                    if event_date_local == today_date:
                        events["today"].append(event_data)
                    else:
                        events["upcoming"].append(event_data)

                except Exception as exc:
                    skipped_fuzzy += 1
                    logger.error(f"Parse error on event {i}: {exc}\n{traceback.format_exc()}")
                    continue

            logger.info(
                f"📊 Done — today={len(events['today'])}, upcoming={len(events['upcoming'])}, "
                f"past_skip={skipped_past}, fuzzy_skip={skipped_fuzzy}, filter_skip={skipped_filter}"
            )
            return {"today": events["today"], "upcoming": events["upcoming"], "today_str": today_str}

        except requests.RequestException as exc:
            logger.error(f"Network error (attempt {attempt + 1}): {exc}")
            if attempt < FOREX_MAX_RETRIES - 1:
                time.sleep(10 * (2 ** attempt))
                continue
            return {"today": [], "upcoming": [], "today_str": ""}
        except ET.ParseError as exc:
            logger.error(f"XML parse error: {exc}")
            return {"today": [], "upcoming": [], "today_str": ""}
        except Exception as exc:
            logger.error(f"Unexpected fetch error: {exc}\n{traceback.format_exc()}")
            return {"today": [], "upcoming": [], "today_str": ""}

    logger.error("All retries exhausted — giving up.")
    return {"today": [], "upcoming": [], "today_str": ""}


def build_embed_dict(events_data: dict) -> dict | None:
    """
    Convert events_data into a Discord embed dict (no discord.py dependency).

    Returns None if there is nothing worth posting.
    """
    from config import (
        FOREX_EMBED_TITLE,
        FOREX_SERVER_NAME,
        FOREX_EMBED_COLOR,
        FOREX_TIMEZONE,
        FOREX_MAX_UPCOMING,
        FOREX_MIN_IMPACT,
        FOREX_CURRENCIES,
        FOREX_MAX_EVENT_TITLE_LENGTH,
    )

    tz_obj = pytz.timezone(FOREX_TIMEZONE)
    now_local = datetime.now(tz_obj)
    tz_display = now_local.strftime("%Z")
    tz_offset = now_local.strftime("%z")
    tz_offset_fmt = f"UTC{tz_offset[:3]}:{tz_offset[3:]}"
    currencies_display = ", ".join(FOREX_CURRENCIES) if FOREX_CURRENCIES else "All"

    today_str = events_data.get("today_str") or now_local.strftime("%Y-%m-%d")

    embed = {
        "title": f"🚨 {FOREX_EMBED_TITLE} — {today_str} ({tz_display})",
        "description": "Weekly economic calendar — stay sharp! 📈",
        "color": FOREX_EMBED_COLOR,
        "fields": [],
        "footer": {
            "text": (
                f"{FOREX_SERVER_NAME} | Grouped by {tz_display} ({tz_offset_fmt}) | "
                f"Min Impact: {FOREX_MIN_IMPACT.upper()} | Currencies: {currencies_display}"
            )
        },
    }

    # ── Today's events ──────────────────────────────────────────────────────
    today_sorted = sorted(events_data["today"], key=lambda x: x["time_local"])
    total_today = len(today_sorted)

    if not today_sorted:
        embed["fields"].append(
            {"name": "📊 Today's News (0 total)", "value": "No matching news for today. 😌", "inline": False}
        )
    else:
        lines_per_field = 5
        num_fields = (total_today + lines_per_field - 1) // lines_per_field
        for fidx in range(num_fields):
            chunk = today_sorted[fidx * lines_per_field : (fidx + 1) * lines_per_field]
            text = ""
            for e in chunk:
                emoji = "🔴" if e["impact"] == "high" else "🟡" if e["impact"] == "medium" else "🟢"
                short = e["event"][:FOREX_MAX_EVENT_TITLE_LENGTH] + "…" if len(e["event"]) > FOREX_MAX_EVENT_TITLE_LENGTH else e["event"]
                text += f"• {e['date_str']} | {e['time_local']} | {e['time_utc']} {emoji} {e['currency']}: [{short}]({e['link']})\n"
            field_name = f"📊 Today's News ({total_today} total)" if fidx == 0 else "\u200b"
            embed["fields"].append({"name": field_name, "value": text, "inline": False})

    # ── Upcoming events ──────────────────────────────────────────────────────
    upcoming_sorted = sorted(events_data["upcoming"], key=lambda x: (x["sort_date"], x["time_local"]))
    total_upcoming = len(upcoming_sorted)
    upcoming_text = "Clear ahead — strategize! 🌤️" if not upcoming_sorted else ""

    for e in upcoming_sorted[:FOREX_MAX_UPCOMING]:
        emoji = "🔴" if e["impact"] == "high" else "🟡" if e["impact"] == "medium" else "🟢"
        short = e["event"][:FOREX_MAX_EVENT_TITLE_LENGTH] + "…" if len(e["event"]) > FOREX_MAX_EVENT_TITLE_LENGTH else e["event"]
        upcoming_text += f"• {e['date_str']} | {e['time_local']} | {e['time_utc']} {emoji} {e['currency']}: [{short}]({e['link']})\n"

    if total_upcoming > FOREX_MAX_UPCOMING:
        remaining = total_upcoming - FOREX_MAX_UPCOMING
        upcoming_text += f"\n**+{remaining} more →** [Full Calendar](https://www.forexfactory.com/calendar)"

    embed["fields"].append(
        {"name": f"🔮 Upcoming ({total_upcoming} total)", "value": upcoming_text, "inline": False}
    )

    # Nothing useful to post
    if total_today == 0 and total_upcoming == 0:
        return None

    return embed
