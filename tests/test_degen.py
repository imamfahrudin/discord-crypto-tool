"""Offline checks for the degen token-lookup module."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.degen.api import _coingecko_date, gecko_network_for
from modules.degen.chart import generate_candlestick_chart
from modules.degen.embeds import create_price_comparison_embed, create_token_embed
from modules.degen.utils import (
    CONTRACT_RE,
    calculate_price_difference,
    extract_money_block,
    format_multiplier,
    format_number,
    format_raw_number,
    get_market_trend,
    parse_formatted_number,
    parse_price_action_id,
    pool_address_from_id,
)


def test_contract_regex_matches_evm_and_solana_only():
    evm = "0x" + "ab" * 20
    sol = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    tx_hash = "0x" + "ab" * 32  # 66 chars, a transaction hash, not a contract
    assert CONTRACT_RE.search(f"check {evm} please").group(1) == evm
    assert CONTRACT_RE.search(sol).group(1) == sol
    assert CONTRACT_RE.search("$BTC") is None
    assert CONTRACT_RE.search("!start vwap") is None
    assert CONTRACT_RE.search("!signal ETH 4h long") is None
    assert CONTRACT_RE.search(tx_hash) is None


def test_number_formatting_matches_degen_embeds():
    assert format_number(None) == "N/A"
    assert format_number(0) == "N/A"
    assert format_number(1500) == "1.5K"
    assert format_number(2_500_000) == "2.5M"
    assert format_raw_number(1234.5, 0) == "1,234"
    assert format_raw_number(0.00001234).startswith("0.000012")
    assert parse_formatted_number("1.5M") == 1_500_000
    assert parse_formatted_number("1,234.00") == 1234.0
    assert get_market_trend(10, 4) == "🟢 Inflow"
    assert get_market_trend("N/A", 1) == "⚪ Stable"
    diff = calculate_price_difference(1, 2)
    assert diff["direction"] == "up"
    assert diff["multiplier"] == 2
    assert format_multiplier(2) == "🚀 2.00x"
    assert format_multiplier(0.5) == "📉 2.00x down"
    assert extract_money_block("```$1,234.50```") == 1234.5


def test_price_button_ids_round_trip():
    address = "0x" + "ab" * 20
    custom_id = f"price_comparison_{address}_polygon_pos_1700000000_123456789012345678"
    parsed = parse_price_action_id(custom_id, "price_comparison_")
    assert parsed == (address, "polygon_pos", 1700000000, "123456789012345678")
    assert parse_price_action_id("price_comparison_broken", "price_comparison_") is None
    sol = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    refresh = f"price_refresh_{sol}_solana_1700000000_123456789012345678"
    assert len(refresh) <= 100


def test_pool_id_keeps_the_address_segment():
    assert pool_address_from_id("eth_0xabc") == "0xabc"
    assert pool_address_from_id("polygon_pos_0xabc") == "0xabc"


def test_chain_and_date_mapping():
    assert gecko_network_for("ethereum") == "eth"
    assert gecko_network_for("avalanche") == "avax"
    assert gecko_network_for("fantom") == "fantom"
    assert _coingecko_date(1700000000) == "14-11-2023"


def test_embeds_keep_original_field_names():
    token = {
        "baseToken": {"name": "Sample", "symbol": "SMP", "address": "0x" + "ab" * 20},
        "chainId": "ethereum",
        "priceUsd": "0.0123",
        "marketCap": 1_500_000,
        "fdv": 2_000_000,
        "liquidity": {"usd": 250000},
        "volume": {"h24": 80_000},
        "priceChange": {"h1": 1.5, "h24": -3.25},
        "txns": {"h24": {"buys": 20}, "h1": {"sells": 5}},
        "url": "https://dexscreener.com/ethereum/0xabc",
    }
    embed = create_token_embed(token)
    names = [field.name for field in embed.fields]
    assert names[0] == "🐋 Market Cap"
    assert "📊 Price" in names
    assert "🏷️ Contract Address" in names
    assert embed.footer.text == "DO YOUR OWN RESEARCH-ALWAYS!"
    assert "🟢 Inflow" in embed.fields[8].value

    comparison = create_price_comparison_embed(
        {**token, "timestamp": 1700000000},
        {**token, "priceUsd": "0.02", "marketCap": 3_000_000},
    )
    comp_names = [field.name for field in comparison.fields]
    assert "💰 Original Price" in comp_names
    assert "🚀 Price Multiplier" in comp_names


def test_chart_png_is_written():
    candles = []
    price = 1.0
    for i in range(30):
        price += 0.01 if i % 2 == 0 else -0.005
        candles.append({
            "timestamp": 1_700_000_000 + i * 3600,
            "open": price,
            "high": price + 0.02,
            "low": price - 0.02,
            "close": price + 0.005,
            "volume": 1000 + i,
        })
    buf = generate_candlestick_chart(
        candles, "Sample", "SMP", "1h", "0x" + "ab" * 20, "eth"
    )
    assert buf is not None
    raw = buf.getvalue()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(raw) > 1000
