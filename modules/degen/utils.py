"""Formatting helpers ported from discord-crypto-degen-tool/src/utils.js."""

import re

# First contract-looking token in a message.
# EVM: 0x + 40 hex. Other chains (Solana and similar): 32–44 alphanumeric chars.
CONTRACT_RE = re.compile(r"\b(0x[a-fA-F0-9]{40}|[A-Za-z0-9]{32,44})\b")

# Money inside a Discord code block, e.g. ```$1,234.00``` or ```$1.5M```.
MONEY_BLOCK_RE = re.compile(r"```\s*\$([0-9,.KMB]+)\s*```", re.IGNORECASE)


def format_number(num):
    """Compact K / M / B formatting. 0 and non-numeric values become N/A."""
    if num is None or num == "" or num is False:
        return "N/A"
    try:
        number = float(num)
    except (TypeError, ValueError):
        return "N/A"
    if number != number:  # NaN
        return "N/A"
    if number == 0:
        return "N/A"

    if number >= 1e9:
        return f"{number / 1e9:.1f}B"
    if number >= 1e6:
        return f"{number / 1e6:.1f}M"
    if number >= 1e3:
        return f"{number / 1e3:.1f}K"
    return str(int(number)) if number.is_integer() else str(number)


def format_raw_number(num, decimals=None):
    """Fixed-decimal grouping, matching the degen embed code blocks."""
    if num is None or num == "" or num is False:
        return "N/A"
    try:
        number = float(num)
    except (TypeError, ValueError):
        return "N/A"
    if number != number or number == 0:
        return "N/A"

    if decimals is None:
        if number < 0.000001:
            decimals = 10
        elif number < 0.001:
            decimals = 8
        elif number < 1:
            decimals = 6
        elif number < 100:
            decimals = 4
        else:
            decimals = 2

    return f"{number:,.{decimals}f}"


def get_market_trend(buys, sells):
    """Buy vs sell flow label. Non-numeric counts are treated as stable."""
    try:
        buys_n = int(buys)
        sells_n = int(sells)
    except (TypeError, ValueError):
        return "⚪ Stable"
    if buys_n > sells_n:
        return "🟢 Inflow"
    if buys_n < sells_n:
        return "🔴 Outflow"
    return "⚪ Stable"


def calculate_price_difference(old_price, new_price):
    """Difference, percent change, multiplier, and direction between two prices."""
    try:
        old_v = float(old_price)
        new_v = float(new_price)
    except (TypeError, ValueError):
        old_v = new_v = 0

    if old_v <= 0 or new_v <= 0:
        return {
            "difference": 0,
            "percentage": 0,
            "multiplier": 1,
            "direction": "stable",
        }

    difference = new_v - old_v
    direction = "stable"
    if difference > 0:
        direction = "up"
    elif difference < 0:
        direction = "down"

    return {
        "difference": difference,
        "percentage": (difference / old_v) * 100,
        "multiplier": new_v / old_v,
        "direction": direction,
    }


def format_price_difference(diff):
    sign = "+" if diff["direction"] == "up" else "-" if diff["direction"] == "down" else ""
    emoji = "📈" if diff["direction"] == "up" else "📉" if diff["direction"] == "down" else "➡️"
    amount = format_number(abs(diff["difference"]))
    return f"{emoji} {sign}${amount} ({sign}{diff['percentage']:.2f}%)"


def format_multiplier(multiplier):
    try:
        multiplier = float(multiplier)
    except (TypeError, ValueError):
        return "N/A"
    if multiplier <= 0:
        return "N/A"
    if multiplier >= 1:
        return f"🚀 {multiplier:.2f}x"
    return f"📉 {(1 / multiplier):.2f}x down"


def parse_formatted_number(formatted_num):
    """Turn 1.5M / 250K / 1,234.00 back into a float."""
    if not formatted_num or not isinstance(formatted_num, str):
        return 0.0

    num_str = formatted_num.replace("$", "").replace(",", "").strip()
    if not num_str:
        return 0.0

    last = num_str[-1].upper()
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    if last in multipliers:
        try:
            return float(num_str[:-1]) * multipliers[last]
        except ValueError:
            return 0.0
    try:
        return float(num_str)
    except ValueError:
        return 0.0


def extract_money_block(field_value):
    """Return the float parsed from a ```$...``` block, or None."""
    if not field_value:
        return None
    match = MONEY_BLOCK_RE.search(field_value)
    if not match:
        return None
    return parse_formatted_number(match.group(1))


def parse_price_action_id(custom_id, prefix):
    """
    Split a price_comparison_ / price_refresh_ custom id.

    Layout: {prefix}{address}_{chainId}_{timestamp}_{requesterId}
    chainId may itself contain underscores (polygon_pos).
    Returns (address, chain_id, timestamp, requester_id) or None.
    """
    if not custom_id.startswith(prefix):
        return None
    parts = custom_id[len(prefix):].split("_")
    if len(parts) < 4:
        return None
    address = parts[0]
    requester_id = parts[-1]
    timestamp_s = parts[-2]
    chain_id = "_".join(parts[1:-2])
    if not address or not chain_id or not timestamp_s.isdigit() or not requester_id.isdigit():
        return None
    return address, chain_id, int(timestamp_s), requester_id


def pool_address_from_id(pool_id):
    """
    GeckoTerminal pool ids look like 'eth_0xabc' or 'polygon_pos_0xabc'.
    The address is the last segment.
    """
    if not pool_id or "_" not in pool_id:
        return pool_id or ""
    return pool_id.split("_")[-1]
