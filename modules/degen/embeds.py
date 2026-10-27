"""Discord embeds and button rows for degen token lookups."""

from datetime import datetime, timezone

import discord

from config import FOOTER_TEXT, PRIMARY_COLOR
from .utils import (
    calculate_price_difference,
    format_multiplier,
    format_number,
    format_price_difference,
    format_raw_number,
    get_market_trend,
)


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def create_token_embed(token):
    """Market snapshot embed. Field layout matches the Node bot."""
    base = token.get("baseToken") or {}
    name = base.get("name") or "Unknown"
    symbol = base.get("symbol") or "?"
    address = base.get("address") or ""
    chain_id = token.get("chainId") or ""
    price_change = token.get("priceChange") or {}
    volume = token.get("volume") or {}
    liquidity = token.get("liquidity") or {}
    txns = token.get("txns") or {}

    h1 = _as_number(price_change.get("h1"))
    h24 = _as_number(price_change.get("h24"))
    change_1h = f"{h1:.2f}%" if h1 is not None else "N/A"
    change_24h = f"{h24:.2f}%" if h24 is not None else "N/A"

    # The original bot paired 24h buys with 1h sells. Keep that pairing.
    buys = (txns.get("h24") or {}).get("buys")
    sells = (txns.get("h1") or {}).get("sells")
    buys_label = "N/A" if buys is None else buys
    sells_label = "N/A" if sells is None else sells
    trend = get_market_trend(buys, sells)

    embed = discord.Embed(
        title=f"{name} ({symbol}) - {str(chain_id).upper()}",
        color=PRIMARY_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🐋 Market Cap", value=f"```${format_raw_number(token.get('marketCap'), 0)}```", inline=True)
    embed.add_field(name="🔐 Liquidity", value=f"```${format_raw_number(liquidity.get('usd'), 0)}```", inline=True)
    embed.add_field(name="⚖️ FDV", value=f"```${format_raw_number(token.get('fdv'), 0)}```", inline=True)
    embed.add_field(name="📈 1h Change", value=f"```   {change_1h}   ```", inline=True)
    embed.add_field(name="💹 24h Change", value=f"```   {change_24h}   ```", inline=True)
    embed.add_field(name="🕒 Volume 24h", value=f"```${format_number(volume.get('h24'))}```", inline=True)
    embed.add_field(name="📊 Price", value=f"```${format_raw_number(token.get('priceUsd'))}```", inline=True)
    embed.add_field(name="🧾 Buys / Sells", value=f"```   {buys_label} / {sells_label}   ```", inline=True)
    embed.add_field(name="💸 Flow Trend", value=f"```   {trend}   ```", inline=True)
    embed.add_field(name="🏷️ Contract Address", value=f"```{address}```", inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _local_time(timestamp):
    try:
        moment = datetime.fromtimestamp(int(timestamp))
    except (TypeError, ValueError, OSError):
        return "unknown time"
    return moment.strftime("%m/%d/%Y, %I:%M:%S %p")


def create_price_comparison_embed(original_data, current_data, historical_data=None):
    """Side-by-side price and market-cap comparison."""
    base = original_data.get("baseToken") or {}
    name = base.get("name") or "Unknown"
    symbol = base.get("symbol") or "?"
    address = base.get("address") or ""
    chain_id = original_data.get("chainId") or ""

    original_price = original_data.get("priceUsd")
    current_price = current_data.get("priceUsd")
    original_mc = original_data.get("marketCap")
    current_mc = current_data.get("marketCap")
    current_volume = (current_data.get("volume") or {}).get("h24")

    price_diff = calculate_price_difference(original_price, current_price)
    mc_diff = calculate_price_difference(original_mc, current_mc)

    if price_diff["direction"] == "up":
        color = 0x00FF00
    elif price_diff["direction"] == "down":
        color = 0xFF0000
    else:
        color = 0x808080

    original_time = _local_time(original_data.get("timestamp"))
    current_time = datetime.now().strftime("%m/%d/%Y, %I:%M:%S %p")

    embed = discord.Embed(
        title=f"📊 {name} ({symbol}) - Price Comparison",
        description=f"Comparing prices from **{original_time}** to **{current_time}** ({str(chain_id).upper()})",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="💰 Original Price", value=f"```${format_raw_number(original_price)}```", inline=True)
    embed.add_field(name="💰 Current Price", value=f"```${format_raw_number(current_price)}```", inline=True)
    embed.add_field(name="📈 Price Change", value=f"```{format_price_difference(price_diff)}```", inline=True)
    embed.add_field(name="🐋 Original Market Cap", value=f"```${format_raw_number(original_mc, 0)}```", inline=True)
    embed.add_field(name="🐋 Current Market Cap", value=f"```${format_raw_number(current_mc, 0)}```", inline=True)
    embed.add_field(name="📊 MC Change", value=f"```{format_price_difference(mc_diff)}```", inline=True)
    embed.add_field(name="🚀 Price Multiplier", value=f"```{format_multiplier(price_diff['multiplier'])}```", inline=True)
    embed.add_field(name="📊 MC Multiplier", value=f"```{format_multiplier(mc_diff['multiplier'])}```", inline=True)
    embed.add_field(name="🕒 Current Volume", value=f"```${format_number(current_volume)}```", inline=True)
    embed.add_field(name="🏷️ Contract Address", value=f"```{address}```", inline=False)
    if historical_data:
        embed.add_field(
            name="📅 Historical Data",
            value="*Data includes historical price information from CoinGecko*",
            inline=False,
        )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _link_button(url):
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    return discord.ui.Button(
        label="🔍 View on DexScreener",
        style=discord.ButtonStyle.link,
        url=url,
    )


def create_token_action_row(url, contract_address, chain_id, timestamp, requester_id):
    """DexScreener link plus Check Current Price. custom_id matches the Node bot."""
    view = discord.ui.View()
    link = _link_button(url)
    if link is not None:
        view.add_item(link)
    custom_id = f"price_comparison_{contract_address}_{chain_id}_{timestamp}_{requester_id}"
    if len(custom_id) <= 100:
        view.add_item(discord.ui.Button(
            label="💰 Check Current Price",
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id,
        ))
    return view


def create_price_comparison_action_row(contract_address, chain_id, original_timestamp, url, requester_id):
    """Refresh, Delete, and DexScreener. custom_ids match the Node bot."""
    view = discord.ui.View()
    refresh_id = f"price_refresh_{contract_address}_{chain_id}_{original_timestamp}_{requester_id}"
    delete_id = f"price_delete_{requester_id}"
    if len(refresh_id) <= 100:
        view.add_item(discord.ui.Button(
            label="🔄 Refresh Price",
            style=discord.ButtonStyle.primary,
            custom_id=refresh_id,
        ))
    if len(delete_id) <= 100:
        view.add_item(discord.ui.Button(
            label="🗑️ Delete",
            style=discord.ButtonStyle.danger,
            custom_id=delete_id,
        ))
    link = _link_button(url)
    if link is not None:
        view.add_item(link)
    return view
