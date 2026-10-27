from datetime import datetime, timezone as dt_timezone, timedelta
import pytz
from config import SESSION_WEIGHTS

SESSIONS_LOCAL = {
    "Sydney":    (9, 18, "Australia/Sydney"),
    "Tokyo":     (9, 18, "Asia/Tokyo"),
    "London":    (8, 17, "Europe/London"),
    "New York":  (8, 17, "America/New_York")
}

def detect_session():
    """Detect current active session based on UTC time and local definitions."""
    now_utc = datetime.now(dt_timezone.utc)
    current_hour_utc = now_utc.hour

    session_priority = ["New York", "London", "Tokyo", "Sydney"]
    for session_name in session_priority:
        start_local, end_local, tz_name = SESSIONS_LOCAL[session_name]
        utc_start, utc_end = get_utc_hours_for_session(start_local, end_local, tz_name, now_utc)

        if utc_start < utc_end:
            if utc_start <= current_hour_utc < utc_end:
                return session_name, SESSION_WEIGHTS.get(session_name, 1.0)
        else:
            if current_hour_utc >= utc_start or current_hour_utc < utc_end:
                return session_name, SESSION_WEIGHTS.get(session_name, 1.0)

    return "London", SESSION_WEIGHTS.get("London", 1.0)

def get_utc_hours_for_session(start_local, end_local, tz_name, reference_date):
    tz = pytz.timezone(tz_name)
    local_date = reference_date.astimezone(tz).date()

    start_local_dt = tz.localize(datetime.combine(local_date, datetime.min.time().replace(hour=start_local)))
    end_local_dt = tz.localize(datetime.combine(local_date, datetime.min.time().replace(hour=end_local)))

    if end_local_dt <= start_local_dt:
        end_local_dt += timedelta(days=1)

    start_utc = start_local_dt.astimezone(dt_timezone.utc).hour
    end_utc = end_local_dt.astimezone(dt_timezone.utc).hour
    return start_utc, end_utc

def session_start_timestamp():
    now = datetime.now(dt_timezone.utc)
    session_name, _ = detect_session()

    if session_name == "Sydney":
        hour = 23
    elif session_name == "Tokyo":
        hour = 0
    elif session_name == "London":
        hour = 7
    else:
        hour = 13

    start = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)

def get_session_flag(session_name: str) -> str:
    flags = {
        'SYDNEY': '🇦🇺',
        'TOKYO': '🇯🇵',
        'LONDON': '🇬🇧',
        'NEW YORK': '🇺🇸',
        'NEW_YORK': '🇺🇸',
        'ASIAN': '🌏',
        'EUROPE': '🇪🇺',
        'ASIA': '🌏'
    }
    return flags.get(session_name.upper(), '')

def get_next_session_info() -> tuple[str, str]:
    now = datetime.now(dt_timezone.utc)
    sessions_order = ["Sydney", "Tokyo", "London", "New York"]
    current_session, _ = detect_session()
    try:
        current_index = sessions_order.index(current_session)
        next_index = (current_index + 1) % len(sessions_order)
        next_session = sessions_order[next_index]
    except ValueError:
        next_session = "London"

    start_local, _, tz_name = SESSIONS_LOCAL[next_session]
    tz = pytz.timezone(tz_name)
    local_date = now.astimezone(tz).date()
    start_local_dt = tz.localize(datetime.combine(local_date, datetime.min.time().replace(hour=start_local)))
    start_utc_dt = start_local_dt.astimezone(dt_timezone.utc)

    if start_utc_dt <= now:
        start_utc_dt += timedelta(days=1)

    time_str = start_utc_dt.strftime("%H:%M UTC")
    return next_session, time_str
