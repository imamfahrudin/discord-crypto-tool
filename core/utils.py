"""
Shared calculation and formatting utilities.
"""

import re
import math
import logging
import ctypes

logger = logging.getLogger("crypto_tool.utils")


def release_memory():
    """Return freed heap pages to the OS (glibc malloc_trim) after heavy matplotlib generation."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def safe_float(v, default=None):
    """Safely convert value to float, returning default on error."""
    try:
        return float(v)
    except Exception:
        return default


def calculate_rr(entry, stop, tp):
    """
    Calculate Risk/Reward Ratio.
    tp can be a multi-line string (with TP1/TP2) or a float/int.
    """
    try:
        entry = float(entry)
        stop = float(stop)
    except Exception:
        return None

    risk = abs(entry - stop)
    if risk < 1e-8:
        return None

    tp_val = None
    if isinstance(tp, str):
        match = re.search(r'TP2:\s*([\d\.]+)', tp)
        if match:
            try:
                tp_val = float(match.group(1))
            except ValueError:
                pass

        if tp_val is None:
            match = re.search(r'TP1:\s*([\d\.]+)', tp)
            if match:
                try:
                    tp_val = float(match.group(1))
                except ValueError:
                    pass
    else:
        try:
            tp_val = float(tp)
        except Exception:
            pass

    if tp_val is None:
        return None

    reward = abs(tp_val - entry)
    return round(reward / risk, 2)


def format_price_dynamic(x):
    """Dynamically format price decimals based on order of magnitude."""
    if not isinstance(x, (float, int)):
        return "-"

    x = float(x)
    abs_x = abs(x)

    if abs_x < 1:
        return f"{x:.8f}".rstrip('0').rstrip('.')
    if abs_x < 10:
        return f"{x:.4f}"
    if abs_x < 1000:
        return f"{x:.3f}"
    return f"{x:.2f}"


def parse_intervals(interval_str: str) -> list[int]:
    """Parse comma-separated interval string into a list of positive integers."""
    try:
        intervals = [int(x.strip()) for x in interval_str.split(',') if x.strip()]
        valid = [i for i in intervals if i > 0]
        return valid if valid else [300]
    except Exception as e:
        logger.warning(f"Invalid interval format '{interval_str}', fallback to [300]: {e}")
        return [300]


def format_interval(seconds: int) -> str:
    """Format interval in seconds to human-readable string (e.g. 2m, 10m, 1h)."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    else:
        hours = seconds / 3600
        if hours == int(hours):
            return f"{int(hours)}h"
        return f"{hours:.1f}h"
