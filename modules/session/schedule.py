"""
Trading-session schedule and embed content.

Hours, colors, and copy follow discord-trading-session-notifier.
Embeds have no footer. Nothing here mentions a role or a webhook.

Session UTC hours are calculated from the fixed local windows (so daylight
saving is applied) and refreshed at 06:00 UTC. One asyncio task in the cog
waits for the next of those times. APScheduler is not used.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pytz import timezone, utc

# Local windows used to derive UTC hours. Colors are the Discord embed accents.
SESSIONS_LOCAL = {
    "Sydney": (9, 18, "Australia/Sydney", 0x8E44AD),
    "Tokyo": (9, 18, "Asia/Tokyo", 0x3498DB),
    "London": (8, 17, "Europe/London", 0x2ECC71),
    "New York": (8, 17, "America/New_York", 0xE74C3C),
}

WIB = "Asia/Jakarta"
SYNC_HOUR_UTC = 6
SYNC_MINUTE_UTC = 0

STARTUP_COLOR = 0x00FFFF
SYNC_COLOR = 0xFFFF00


def format_time_with_offset(dt: datetime) -> str:
    """Format datetime as 'HH:MM DD-MM-YYYY UTC±HH:MM'."""
    offset = dt.strftime("%z")
    return dt.strftime("%H:%M %d-%m-%Y UTC") + offset[:3] + ":" + offset[3:]


def compute_sessions(now_utc: datetime | None = None) -> dict:
    """
    UTC start/end hours for each session on the UTC calendar date of now.

    Returns name → (start_utc_hour, end_utc_hour, tz_name, color).
    """
    if now_utc is None:
        now_utc = datetime.now(utc)
    today = now_utc.date()
    updated = {}
    for name, (start_local, end_local, tz_name, color) in SESSIONS_LOCAL.items():
        tz = timezone(tz_name)
        local_midnight = tz.localize(datetime(today.year, today.month, today.day, 0, 0, 0))
        start_local_dt = local_midnight.replace(hour=start_local)
        end_local_dt = local_midnight.replace(hour=end_local)
        if end_local_dt <= start_local_dt:
            end_local_dt += timedelta(days=1)
        start_utc = start_local_dt.astimezone(utc).hour
        end_utc = end_local_dt.astimezone(utc).hour
        updated[name] = (start_utc, end_utc, tz_name, color)
    return updated


def session_changes(old: dict, new: dict) -> list[str]:
    """Lines describing UTC windows that differ. Empty when nothing moved."""
    changes = []
    for name, (start, end, _, _) in new.items():
        old_start, old_end, _, _ = old.get(name, (0, 0, "", 0))
        if start != old_start or end != old_end:
            changes.append(f"{name}: {start:02d}:00-{end:02d}:00 UTC")
    return changes


def get_active_session(sessions: dict, current_hour_utc: int) -> str | None:
    """First session whose window contains this UTC hour, or None."""
    for name, (start, end, _, _) in sessions.items():
        if start < end:
            if start <= current_hour_utc < end:
                return name
        elif current_hour_utc >= start or current_hour_utc < end:
            return name
    return None


def session_hours_wib(sessions: dict, now_utc: datetime) -> list[str]:
    """'Name: HH:MM → HH:MM WIB' for every session."""
    wib = timezone(WIB)
    lines = []
    for name, (start_utc, end_utc, _, _) in sessions.items():
        today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        start_dt_utc = today_utc + timedelta(hours=start_utc)
        end_dt_utc = today_utc + timedelta(hours=end_utc)
        if end_dt_utc <= start_dt_utc:
            end_dt_utc += timedelta(days=1)
        start_wib = start_dt_utc.astimezone(wib).strftime("%H:%M")
        end_wib = end_dt_utc.astimezone(wib).strftime("%H:%M")
        lines.append(f"{name}: {start_wib} → {end_wib} WIB")
    return lines


def next_utc(now: datetime, hour: int, minute: int = 0) -> datetime:
    """Next occurrence of hour:minute UTC strictly after now."""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def next_event_batch(sessions: dict, now: datetime) -> tuple[datetime, list[tuple]]:
    """
    The soonest wake-up and every job that shares that timestamp.

    Each item is ("sync", when, None) or ("session", when, session_name).
    Sync is listed before a session that starts on the same minute.
    """
    events = [("sync", next_utc(now, SYNC_HOUR_UTC, SYNC_MINUTE_UTC), None)]
    for name, (hour_utc, _, _, _) in sessions.items():
        events.append(("session", next_utc(now, hour_utc, 0), name))
    earliest = min(event[1] for event in events)
    batch = [event for event in events if event[1] == earliest]
    batch.sort(key=lambda event: 0 if event[0] == "sync" else 1)
    return earliest, batch


def startup_embed(sessions: dict, now_utc: datetime | None = None) -> dict:
    """Confirmation embed sent by !start session. No footer."""
    if now_utc is None:
        now_utc = datetime.now(utc)
    wib_time = now_utc.astimezone(timezone(WIB))
    active = get_active_session(sessions, now_utc.hour)
    return {
        "title": "✅ Trading Session Notifier Started",
        "color": STARTUP_COLOR,
        "fields": [
            {
                "name": "📈 Current Active Session",
                "value": active if active else "None",
                "inline": False,
            },
            {"name": "🕒 Now (UTC)", "value": format_time_with_offset(now_utc), "inline": False},
            {"name": "🇮🇩 Indonesia (WIB)", "value": format_time_with_offset(wib_time), "inline": False},
            {
                "name": "📅 All Session Hours (WIB)",
                "value": "\n".join(session_hours_wib(sessions, now_utc)),
                "inline": False,
            },
        ],
        "timestamp": now_utc.isoformat(),
    }


def session_start_embed(session_name: str, sessions: dict, now_utc: datetime | None = None) -> dict:
    """Embed posted when a session's UTC start hour is reached. No footer."""
    if now_utc is None:
        now_utc = datetime.now(utc)
    start, end, session_tz_name, color = sessions[session_name]
    session_time = now_utc.astimezone(timezone(session_tz_name))
    wib_time = now_utc.astimezone(timezone(WIB))
    return {
        "title": f"{session_name} Trading Session Started",
        "color": color,
        "fields": [
            {
                "name": "🕒 Session Time Range (UTC)",
                "value": f"{start:02d}:00 → {end:02d}:00",
                "inline": False,
            },
            {"name": "🕒 Now (UTC)", "value": format_time_with_offset(now_utc), "inline": False},
            {"name": f"🌐 {session_tz_name}", "value": format_time_with_offset(session_time), "inline": False},
            {"name": "🇮🇩 Indonesia (WIB)", "value": format_time_with_offset(wib_time), "inline": False},
        ],
        "timestamp": now_utc.isoformat(),
    }


def sync_embed(changes: list[str], now_utc: datetime | None = None) -> dict:
    """Embed posted at 06:00 UTC when a daylight-saving shift moves a window. No footer."""
    if now_utc is None:
        now_utc = datetime.now(utc)
    wib_time = now_utc.astimezone(timezone(WIB))
    return {
        "title": "🔄 Trading Sessions Updated",
        "color": SYNC_COLOR,
        "fields": [
            {"name": "🕒 Updated Sessions (UTC)", "value": "\n".join(changes), "inline": False},
            {"name": "🕒 Now (UTC)", "value": format_time_with_offset(now_utc), "inline": False},
            {"name": "🇮🇩 Indonesia (WIB)", "value": format_time_with_offset(wib_time), "inline": False},
        ],
        "timestamp": now_utc.isoformat(),
    }
