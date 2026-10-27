"""
DegenCog

Listens for a pasted contract address and for the price buttons attached to
its reply. Nothing here is registered as !start / !stop, and nothing is written
to the VWAP or Forex channel tables. Button state (address, chain, time,
requester) lives in the Discord custom_id.
"""

import asyncio
import concurrent.futures
import logging
import re
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands

from config import CHART_TIMEFRAME_HOURS, DEGEN_CONCURRENCY
from .api import (
    fetch_coin_image,
    fetch_historical_price,
    fetch_ohlc_data,
    fetch_token_data,
    gecko_network_for,
    search_pools_by_token,
)
from .chart import generate_candlestick_chart
from .embeds import (
    create_price_comparison_action_row,
    create_price_comparison_embed,
    create_token_action_row,
    create_token_embed,
)
from .utils import (
    CONTRACT_RE,
    extract_money_block,
    parse_price_action_id,
    pool_address_from_id,
)

logger = logging.getLogger("crypto_tool.degen")

USAGE_BUTTON = "⚠️ That button is invalid. Paste the token contract address again."
CHART_NO_DATA = "📊 *Chart not available - insufficient trading data*"
CHART_NO_POOLS = "📊 *Chart not available - no liquidity pools found*"
CHART_FAILED = "📊 *Chart not available - insufficient historical data*"


def _field_is_price(name):
    return "Price" in name and "Change" not in name and "Multiplier" not in name


def _field_is_market_cap(name):
    return "Market Cap" in name and "Change" not in name and "Multiplier" not in name


def _prices_from_embed(embed, price_pred, mcap_pred):
    """Walk embed fields and return (price, market_cap). Later matches win, as in the Node bot."""
    price = None
    market_cap = None
    if embed is None:
        return price, market_cap
    for field in embed.fields:
        if price_pred(field.name):
            parsed = extract_money_block(field.value)
            if parsed:
                price = parsed
        if mcap_pred(field.name):
            parsed = extract_money_block(field.value)
            if parsed:
                market_cap = parsed
    return price, market_cap


class DegenCog(commands.Cog):
    """On-demand DEX token lookup. No prefix commands and no channel scanner state."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = None
        self.semaphore = asyncio.Semaphore(DEGEN_CONCURRENCY)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="degen-chart")

    async def cog_load(self):
        timeout = aiohttp.ClientTimeout(total=20)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "discord-crypto-tool/degen",
            },
        )

    async def cog_unload(self):
        if self.session is not None and not self.session.closed:
            await self.session.close()
        self.executor.shutdown(wait=False)

    async def handle_token_query(self, message: discord.Message):
        """Reply when the message contains a contract address. Silent otherwise."""
        match = CONTRACT_RE.search(message.content or "")
        if not match:
            return
        async with self.semaphore:
            await self._reply_with_token(message, match.group(1))

    async def _reply_with_token(self, message, contract_address):
        try:
            token_data = await fetch_token_data(self.session, contract_address)
            if not token_data:
                await message.reply("🚫 Token not found.")
                return

            image_url = (token_data.get("info") or {}).get("imageUrl")
            if not image_url:
                try:
                    image_url = await fetch_coin_image(
                        self.session, contract_address, token_data.get("chainId")
                    )
                except Exception as exc:
                    logger.info("Failed to fetch coin image: %s", exc)

            chart_file = None
            chart_status = None
            try:
                chart_file, chart_status = await self._build_chart(token_data, contract_address)
            except Exception as exc:
                chart_status = CHART_FAILED
                base = token_data.get("baseToken") or {}
                logger.info("Chart generation failed, continuing without chart: %s", chart_status)
                logger.info("Chart error details: %s", exc)
                logger.info(
                    "Token: %s (%s) on %s",
                    base.get("symbol"),
                    contract_address,
                    token_data.get("chainId"),
                )

            embed = create_token_embed(token_data)
            if image_url:
                embed.set_thumbnail(url=image_url)
            if chart_status and chart_file is None:
                embed.add_field(name="📊 Chart Status", value=chart_status, inline=False)

            base = token_data.get("baseToken") or {}
            view = create_token_action_row(
                token_data.get("url"),
                base.get("address") or contract_address,
                token_data.get("chainId") or "unknown",
                int(datetime.now(tz=timezone.utc).timestamp()),
                message.author.id,
            )

            kwargs = {"embed": embed, "view": view}
            if chart_file is not None:
                embed.set_image(url=f"attachment://{chart_file.filename}")
                kwargs["file"] = chart_file

            await message.reply(**kwargs)
        except Exception as exc:
            logger.error("Error processing token query: %s", exc, exc_info=True)
            try:
                await message.reply("❌ Failed to fetch token data. Please try again later.")
            except Exception:
                pass

    async def _build_chart(self, token_data, contract_address):
        network = gecko_network_for(token_data.get("chainId"))
        base = token_data.get("baseToken") or {}
        symbol = base.get("symbol") or "TOKEN"
        name = base.get("name") or symbol

        pools = await search_pools_by_token(self.session, network, contract_address)
        if not pools:
            logger.info("No pools found for %s on %s", symbol, network)
            return None, CHART_NO_POOLS

        pool_address = pool_address_from_id(pools[0].get("id") or "")
        if not pool_address:
            return None, CHART_NO_POOLS

        ohlc = await fetch_ohlc_data(
            self.session, network, pool_address, "hour", CHART_TIMEFRAME_HOURS
        )
        if not ohlc:
            logger.info("No OHLC data available for %s on %s", symbol, network)
            return None, CHART_NO_DATA

        loop = asyncio.get_running_loop()
        chart_buf = await loop.run_in_executor(
            self.executor,
            generate_candlestick_chart,
            ohlc,
            name,
            symbol,
            "1h",
            contract_address,
            network,
        )
        if chart_buf is None:
            return None, CHART_FAILED

        safe_symbol = re.sub(r"[^A-Za-z0-9._-]", "", symbol) or "token"
        return discord.File(chart_buf, filename=f"{safe_symbol}_chart.png"), None

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Price buttons. Screening's ema_switch: buttons are ignored here."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id") or ""
        if custom_id.startswith("price_comparison_"):
            await self._handle_price_comparison(interaction, custom_id)
        elif custom_id.startswith("price_refresh_"):
            await self._handle_price_refresh(interaction, custom_id)
        elif custom_id.startswith("price_delete_"):
            await self._handle_price_delete(interaction, custom_id)

    async def _handle_price_comparison(self, interaction, custom_id):
        parsed = parse_price_action_id(custom_id, "price_comparison_")
        if parsed is None:
            await interaction.response.send_message(USAGE_BUTTON, ephemeral=True)
            return

        contract_address, chain_id, original_timestamp, requester_id = parsed
        is_authorized = str(interaction.user.id) == requester_id

        if interaction.response.is_done():
            return
        # thinking=True is deferReply: a new message. The token embed stays as posted.
        # A plain defer() on a button would edit that original message instead.
        await interaction.response.defer(ephemeral=not is_authorized, thinking=True)

        try:
            current_data = await fetch_token_data(self.session, contract_address)
            if not current_data:
                await interaction.edit_original_response(content="🚫 Unable to fetch current token data.")
                return

            original_message = interaction.message
            if original_message is None or not original_message.embeds:
                await interaction.edit_original_response(content="🚫 Unable to find original message.")
                return

            original_price, original_mc = _prices_from_embed(
                original_message.embeds[0], _field_is_price, _field_is_market_cap
            )
            original_data = dict(current_data)
            original_data["priceUsd"] = original_price or current_data.get("priceUsd")
            original_data["marketCap"] = original_mc or current_data.get("marketCap")
            original_data["timestamp"] = original_timestamp

            historical = await fetch_historical_price(
                self.session, contract_address, chain_id, original_timestamp
            )
            if historical and historical.get("price"):
                original_data["priceUsd"] = historical["price"]
                original_data["marketCap"] = historical.get("marketCap")

            embed = create_price_comparison_embed(original_data, current_data, historical)
            view = create_price_comparison_action_row(
                contract_address,
                chain_id,
                original_timestamp,
                current_data.get("url"),
                interaction.user.id,
            )
            content = None if is_authorized else "🔒 *Private price comparison (only visible to you)*"
            await interaction.edit_original_response(content=content, embed=embed, view=view)
        except Exception as exc:
            logger.error("Error handling price comparison: %s", exc, exc_info=True)
            try:
                await interaction.edit_original_response(
                    content="❌ Failed to generate price comparison. Please try again later."
                )
            except Exception:
                pass

    async def _original_snapshot(self, interaction, contract_address, chain_id, original_timestamp, current_data):
        """
        Recover the posted price. Prefer the message this comparison replies to.
        If Discord did not store a reference, read the Original Price fields on
        this comparison embed.
        """
        source = None
        reference = interaction.message.reference if interaction.message else None
        if reference is not None and reference.message_id and interaction.channel is not None:
            try:
                source = await interaction.channel.fetch_message(reference.message_id)
            except Exception as exc:
                logger.info("Could not fetch referenced degen message: %s", exc)

        if source is not None and source.embeds:
            original_price, original_mc = _prices_from_embed(
                source.embeds[0], _field_is_price, _field_is_market_cap
            )
        else:
            original_price, original_mc = _prices_from_embed(
                interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None,
                lambda name: "Original Price" in name,
                lambda name: "Original Market Cap" in name,
            )
            if original_price is None and original_mc is None:
                return None

        original_data = dict(current_data)
        original_data["priceUsd"] = original_price or current_data.get("priceUsd")
        original_data["marketCap"] = original_mc or current_data.get("marketCap")
        original_data["timestamp"] = original_timestamp

        historical = await fetch_historical_price(
            self.session, contract_address, chain_id, original_timestamp
        )
        if historical and historical.get("price"):
            original_data["priceUsd"] = historical["price"]
            original_data["marketCap"] = historical.get("marketCap")
        return original_data, historical

    async def _handle_price_refresh(self, interaction, custom_id):
        parsed = parse_price_action_id(custom_id, "price_refresh_")
        if parsed is None:
            await interaction.response.send_message(USAGE_BUTTON, ephemeral=True)
            return

        contract_address, chain_id, original_timestamp, requester_id = parsed
        if str(interaction.user.id) != requester_id:
            await interaction.response.send_message(
                "❌ Only the person who requested this price comparison can refresh it.",
                ephemeral=True,
            )
            return

        if interaction.response.is_done():
            return
        await interaction.response.defer()

        try:
            current_data = await fetch_token_data(self.session, contract_address)
            if not current_data:
                await interaction.edit_original_response(
                    content="🚫 Unable to fetch current token data.",
                    embed=None,
                    view=None,
                )
                return

            snapshot = await self._original_snapshot(
                interaction, contract_address, chain_id, original_timestamp, current_data
            )
            if snapshot is None:
                await interaction.edit_original_response(
                    content="🚫 Unable to find original message for comparison.",
                    embed=None,
                    view=None,
                )
                return

            original_data, historical = snapshot
            embed = create_price_comparison_embed(original_data, current_data, historical)
            view = create_price_comparison_action_row(
                contract_address,
                chain_id,
                original_timestamp,
                current_data.get("url"),
                interaction.user.id,
            )
            await interaction.edit_original_response(content=None, embed=embed, view=view)
        except Exception as exc:
            logger.error("Error refreshing price comparison: %s", exc, exc_info=True)
            try:
                await interaction.edit_original_response(
                    content="❌ Failed to refresh price comparison. Please try again later.",
                    embed=None,
                    view=None,
                )
            except Exception:
                pass

    async def _handle_price_delete(self, interaction, custom_id):
        prefix = "price_delete_"
        if not custom_id.startswith(prefix):
            await interaction.response.send_message(USAGE_BUTTON, ephemeral=True)
            return
        requester_id = custom_id[len(prefix):]
        if not requester_id.isdigit() or str(interaction.user.id) != requester_id:
            await interaction.response.send_message(
                "❌ Only the person who requested this price comparison can delete it.",
                ephemeral=True,
            )
            return

        try:
            await interaction.message.delete()
        except Exception as exc:
            logger.error("Error deleting message: %s", exc)
            if not interaction.response.is_done():
                await interaction.response.defer()
