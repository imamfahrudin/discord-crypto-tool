"""
VWAP Cog for discord-crypto-tool.
Manages continuous live-updating VWAP scanner tables, session monitoring, state persistence, and !start/!stop/!session/!health.
"""

import discord
from discord.ext import commands
import asyncio
import aiohttp
import os
import logging
import traceback
from datetime import datetime, timedelta, timezone

from config import (
    MAX_SYMBOLS,
    REFRESH_INTERVAL,
    MIN_VOLUME_M,
    CANDLE_FETCH_CONCURRENCY,
    ENABLE_WEBSOCKET_PRICES,
    TABLE_FOOTER_TEXT,
    EMBED_FOOTER_TEXT,
    UPDATE_STAGGER_DELAY,
    TOP_N
)
from core.database import (
    save_channel_state,
    load_channel_states,
    remove_channel_state
)
from core.rate_limiter import rate_limiter
from core.utils import parse_intervals, format_interval
from .sessions.session_manager import detect_session, session_start_timestamp, get_session_flag, get_next_session_info
from .sessions.vwap import calculate_vwap
from .indicators.rsi import rsi
from .indicators.macd import macd_hist
from .indicators.atr import atr
from .indicators.stochastic import stochastic
from .engine.scanner_engine import scan
from .output.table import render_table
from .table_generator import generate_table_image
from .bybit.rest import get_futures_symbols, get_session_candles
from .bybit.websocket import start_ws, prices

logger = logging.getLogger("crypto_tool.vwap.cog")


class VwapCog(commands.Cog):
    """Cog managing automated VWAP session scanning and persistent live Discord tables."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_states = {}  # channel_id -> {interval: {'message': Message, 'running': bool, 'task': Task, ...}}
        self.current_session = None
        self.session_check_task = None
        self.cache_updater_task = None
        self.ws_started = False

        self.scanner_cache = {
            'data': None,
            'last_updated': 0,
            'last_successful_update': 0,
            'updating': False
        }
        self.force_fresh_data = True

    async def on_bot_ready(self):
        """Called by core/bot.py once bot gateway connection is fully open."""
        logger.info("Initializing VWAP Cog background tasks...")

        # 1. Start background cache updater
        if self.cache_updater_task is None or self.cache_updater_task.done():
            self.cache_updater_task = asyncio.create_task(self.cache_updater_loop())
            logger.info("✅ VWAP scanner cache updater loop started")

        # 2. Start session change monitor
        if self.session_check_task is None or self.session_check_task.done():
            self.session_check_task = asyncio.create_task(self.monitor_session_changes())
            logger.info("✅ VWAP session monitor loop started")

        # 3. Optional real-time WebSocket prices stream
        if ENABLE_WEBSOCKET_PRICES and not self.ws_started:
            try:
                symbols = (await get_futures_symbols())[:MAX_SYMBOLS]
                start_ws(symbols)
                self.ws_started = True
                logger.info(f"✅ Bybit WebSocket ticker stream started for {len(symbols)} pairs")
            except Exception as e:
                logger.error(f"❌ Failed to start Bybit WebSocket stream: {e}")

        # 4. Restore active channels from SQLite
        await self.restore_channel_states()

    def cog_unload(self):
        """Cleanup when cog is unloaded."""
        if self.cache_updater_task:
            self.cache_updater_task.cancel()
        if self.session_check_task:
            self.session_check_task.cancel()
        for cid, intervals in self.channel_states.items():
            for interval, state in intervals.items():
                if state.get('task'):
                    state['task'].cancel()

    # -----------------------------------------------------------------------
    # Scanner Computation & Cache
    # -----------------------------------------------------------------------
    async def get_scanner_data_raw(self):
        """Execute heavy scanning pipeline across Bybit linear futures."""
        symbols = (await get_futures_symbols())[:MAX_SYMBOLS]
        session_name, weight = detect_session()
        current_session_start = session_start_timestamp()

        now = datetime.now(timezone.utc)
        current_session_start_time = datetime.fromtimestamp(current_session_start / 1000, timezone.utc)
        hours_elapsed = (now - current_session_start_time).total_seconds() / 3600

        # If current session has less than 2 hours elapsed, merge with previous session for candle depth
        if hours_elapsed < 2:
            if session_name == "Tokyo":
                prev_session_start = int((now - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0).timestamp() * 1000)
            elif session_name == "London":
                prev_session_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            elif session_name == "New York":
                prev_session_start = int(now.replace(hour=7, minute=0, second=0, microsecond=0).timestamp() * 1000)
            else:
                prev_session_start = int((now - timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0).timestamp() * 1000)
            start_ts = prev_session_start
        else:
            start_ts = current_session_start

        connector = aiohttp.TCPConnector(limit=CANDLE_FETCH_CONCURRENCY)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [get_session_candles(session, s, "5", start_ts) for s in symbols]
            candle_sets = await asyncio.gather(*tasks)

            market = []
            for s, candles in zip(symbols, candle_sets):
                if not candles or len(candles) < 20:
                    continue

                closes = [c["close"] for c in candles]
                highs  = [c["high"] for c in candles]
                lows   = [c["low"] for c in candles]

                price = prices.get(s, closes[-1])
                vwap = calculate_vwap(candles)
                if not price or not vwap:
                    continue

                volumes = [c.get("volume", 0) * c.get("close", 0) for c in candles]
                total_volume = sum(volumes)
                if total_volume <= 0:
                    continue

                volume_m = total_volume / 1_000_000
                if volume_m < MIN_VOLUME_M:
                    continue

                market.append({
                    "symbol": s,
                    "price": price,
                    "vwap": vwap,
                    "volume_m": round(volume_m, 2),
                    "trend": "ABOVE VWAP" if price > vwap else "BELOW VWAP",
                    "vwap_dev": round((price - vwap) / vwap * 100, 2),
                    "rsi": rsi(closes),
                    "macd": macd_hist(closes),
                    "atr": atr(highs, lows, closes),
                    "stoch": stochastic(highs, lows, closes),
                })

            ranked = scan(market, session_name, weight)
            return render_table(ranked[:TOP_N], session_name, weight)

    async def update_scanner_cache(self):
        """Update scanner cache in background."""
        if self.scanner_cache['updating']:
            return
        self.scanner_cache['updating'] = True
        try:
            data = await self.get_scanner_data_raw()
            if data:
                self.scanner_cache['data'] = data
                self.scanner_cache['last_updated'] = asyncio.get_running_loop().time()
                self.scanner_cache['last_successful_update'] = asyncio.get_running_loop().time()
                logger.info("✅ VWAP scanner cache updated successfully")
        except Exception as e:
            logger.error(f"❌ Failed to update VWAP scanner cache: {e}")
        finally:
            self.scanner_cache['updating'] = False

    async def get_scanner_data(self):
        """Return fresh cached scanner data or trigger update."""
        current_time = asyncio.get_running_loop().time()
        cache_fresh = self.scanner_cache['data'] and (current_time - self.scanner_cache['last_updated']) < 30

        if not self.force_fresh_data and cache_fresh:
            wib = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime('%H:%M:%S')
            utc = datetime.now(timezone.utc).strftime('%H:%M:%S')
            return self.scanner_cache['data'], f"{wib} WIB | {utc} UTC"

        await self.update_scanner_cache()
        self.force_fresh_data = False

        if self.scanner_cache['data']:
            wib = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime('%H:%M:%S')
            utc = datetime.now(timezone.utc).strftime('%H:%M:%S')
            return self.scanner_cache['data'], f"{wib} WIB | {utc} UTC"
        else:
            return "⚠️ Scanner data not available. Please try again shortly.", "N/A"

    async def cache_updater_loop(self):
        """Periodic background updater for scanner cache."""
        intervals = parse_intervals(REFRESH_INTERVAL)
        min_interval = min(intervals)
        logger.info(f"VWAP cache updater interval: {min_interval}s")

        while True:
            try:
                await self.update_scanner_cache()
                await asyncio.sleep(min_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in VWAP cache updater: {e}")
                await asyncio.sleep(10)

    # -----------------------------------------------------------------------
    # Channel State Restoration & Update Loops
    # -----------------------------------------------------------------------
    async def restore_channel_states(self):
        """Restore active running scanner tables from SQLite."""
        saved_states = load_channel_states()
        if not saved_states:
            logger.info("ℹ️ No previous VWAP channel states to restore")
            return

        total = sum(len(ivs) for ivs in saved_states.values())
        logger.info(f"🔄 Restoring {total} scanner state(s) across {len(saved_states)} channel(s)...")

        for channel_id, intervals_data in saved_states.items():
            for interval, state_data in intervals_data.items():
                try:
                    channel = self.bot.get_channel(channel_id)
                    if not channel and state_data.get('guild_id'):
                        guild = self.bot.get_guild(state_data['guild_id'])
                        if guild:
                            channel = guild.get_channel(channel_id)

                    if not channel:
                        logger.warning(f"⚠️ Channel {channel_id} not accessible, removing from database")
                        remove_channel_state(channel_id, interval)
                        continue

                    try:
                        message = await channel.fetch_message(state_data['message_id'])
                    except discord.NotFound:
                        logger.warning(f"⚠️ Message {state_data['message_id']} not found in {channel_id}, removing")
                        remove_channel_state(channel_id, interval)
                        continue

                    if channel_id not in self.channel_states:
                        self.channel_states[channel_id] = {}

                    self.channel_states[channel_id][interval] = {
                        'message': message,
                        'running': True,
                        'task': None,
                        'last_scheduled_update': datetime.now(),
                        'reset_timer_event': asyncio.Event()
                    }

                    task = asyncio.create_task(self.update_loop_for_channel(channel_id, interval))
                    self.channel_states[channel_id][interval]['task'] = task
                    logger.info(f"✅ Restored scanner in #{channel.name} [{interval}s]")
                    await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"❌ Failed to restore scanner {channel_id} [{interval}s]: {e}")
                    remove_channel_state(channel_id, interval)

    async def update_loop_for_channel(self, channel_id: int, interval: int):
        """Continuous update loop for an active table message."""
        logger.info(f"🔄 Update loop started for channel {channel_id} interval {interval}s")
        interval_str = format_interval(interval)
        first_update = True
        consecutive_failures = 0
        max_consecutive_failures = 5

        while (channel_id in self.channel_states and
               interval in self.channel_states[channel_id] and
               self.channel_states[channel_id][interval]['running']):
            try:
                scanner_data, last_updated = await self.get_scanner_data()
                session_name, weight = detect_session()
                session_flag = get_session_flag(session_name)
                next_session_name, next_session_time = get_next_session_info()
                next_session_flag = get_session_flag(next_session_name)

                next_update_dt = datetime.now() + timedelta(seconds=interval)
                next_update_str = next_update_dt.strftime('%H:%M:%S WIB')

                table_image = generate_table_image(
                    table_data=scanner_data,
                    session_name=session_name,
                    weight=str(weight),
                    last_updated=last_updated,
                    footer_text=TABLE_FOOTER_TEXT,
                    interval_str=interval_str,
                    next_update=next_update_str
                )

                if table_image:
                    embed = discord.Embed(
                        title=f"BYBIT FUTURES VWAP SCANNER — EVERY {interval_str.upper()}",
                        description=(
                            f"**Current Session:** {session_name} {session_flag}\n"
                            f"**Weight:** {weight}\n"
                            f"**Last Updated:** {last_updated}\n"
                            f"**Next Update:** {next_update_str}\n"
                            f"**Next Session:** {next_session_name} {next_session_flag} at {next_session_time}"
                        ),
                        color=discord.Color.blue()
                    )

                    filename = f"vwap_scanner_{interval}s_{datetime.utcnow().strftime('%H%M%S')}.png"
                    file = discord.File(table_image, filename=filename)
                    embed.set_image(url=f"attachment://{filename}")

                    if EMBED_FOOTER_TEXT:
                        embed.set_footer(text=EMBED_FOOTER_TEXT)

                    message = self.channel_states[channel_id][interval]['message']
                    await rate_limiter.acquire(message.id)
                    await message.edit(embed=embed, attachments=[file])
                    self.channel_states[channel_id][interval]['last_scheduled_update'] = datetime.now()
                    consecutive_failures = 0

            except discord.NotFound:
                logger.error(f"Message not found in channel {channel_id} interval {interval}s, stopping")
                if channel_id in self.channel_states and interval in self.channel_states[channel_id]:
                    del self.channel_states[channel_id][interval]
                    if not self.channel_states[channel_id]:
                        del self.channel_states[channel_id]
                remove_channel_state(channel_id, interval)
                break
            except discord.HTTPException as e:
                consecutive_failures += 1
                if getattr(e, 'code', None) == 429:
                    retry_after = getattr(e, 'retry_after', 60)
                    await asyncio.sleep(min(retry_after * 1.5, 300))
                elif consecutive_failures >= max_consecutive_failures:
                    break
                else:
                    await asyncio.sleep(10)
                continue
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Error updating message in channel {channel_id}: {e}")
                if consecutive_failures >= max_consecutive_failures:
                    break
                await asyncio.sleep(15)
                continue

            # Wait for next update or reset event (session change)
            reset_event = self.channel_states[channel_id][interval]['reset_timer_event']
            try:
                await asyncio.wait_for(reset_event.wait(), timeout=interval)
                reset_event.clear()
            except asyncio.TimeoutError:
                pass

    async def monitor_session_changes(self):
        """Monitor trading session transitions and trigger immediate refresh."""
        await asyncio.sleep(5)
        try:
            self.current_session, _ = detect_session()
        except Exception:
            self.current_session = "Unknown"

        while True:
            try:
                await asyncio.sleep(60)
                new_session, new_weight = detect_session()
                if new_session != self.current_session:
                    logger.info(f"🔄 SESSION TRANSITION: {self.current_session} → {new_session} (Weight: {new_weight})")
                    self.current_session = new_session
                    await self.trigger_all_updates()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session monitor: {e}")
                await asyncio.sleep(60)

    async def trigger_all_updates(self):
        """Trigger immediate update for all active scanners with staggering."""
        tasks_to_trigger = []
        for channel_id, intervals in self.channel_states.items():
            for interval, state in intervals.items():
                if state.get('running') and state.get('reset_timer_event'):
                    tasks_to_trigger.append((channel_id, interval, state['reset_timer_event']))

        for idx, (cid, interval, evt) in enumerate(tasks_to_trigger):
            evt.set()
            if idx < len(tasks_to_trigger) - 1 and UPDATE_STAGGER_DELAY > 0:
                await asyncio.sleep(UPDATE_STAGGER_DELAY)

    # -----------------------------------------------------------------------
    # Commands: !start, !stop, !session, !health
    # -----------------------------------------------------------------------
    @commands.command(name="start")
    async def start_command(self, ctx):
        """Start continuous live-updating VWAP tables in this channel."""
        channel_id = ctx.channel.id
        intervals = parse_intervals(REFRESH_INTERVAL)

        if channel_id in self.channel_states and self.channel_states[channel_id]:
            existing = list(self.channel_states[channel_id].keys())
            intervals_str = ', '.join(format_interval(i) for i in existing)
            await ctx.message.add_reaction("⚠️")
            await ctx.send(f"🔄 VWAP scanner sudah aktif di channel ini!\nInterval aktif: `{intervals_str}`")
            return

        try:
            await ctx.message.add_reaction("✅")
            if channel_id not in self.channel_states:
                self.channel_states[channel_id] = {}

            server_name = ctx.guild.name if ctx.guild else "DM"
            guild_id = ctx.guild.id if ctx.guild else None

            for interval in intervals:
                interval_str = format_interval(interval)
                embed = discord.Embed(
                    title=f"VWAP Scanner [{interval_str}]",
                    description=f"Starting VWAP scanner with {interval_str} refresh interval...\nMemuat data pasar...",
                    color=discord.Color.blue()
                )
                message = await ctx.send(embed=embed)

                self.channel_states[channel_id][interval] = {
                    'message': message,
                    'running': True,
                    'task': None,
                    'last_scheduled_update': datetime.now(),
                    'reset_timer_event': asyncio.Event()
                }

                save_channel_state(channel_id, interval, message.id, True, server_name, ctx.channel.name, guild_id)
                task = asyncio.create_task(self.update_loop_for_channel(channel_id, interval))
                self.channel_states[channel_id][interval]['task'] = task

            intervals_str = ', '.join(format_interval(i) for i in intervals)
            logger.info(f"✅ Scanner started in #{ctx.channel.name} with intervals: {intervals_str}")

        except Exception as e:
            logger.error(f"Error in start_command: {e}")
            await ctx.send(f"❌ Error starting scanner: {str(e)[:100]}")

    @commands.command(name="stop")
    async def stop_command(self, ctx):
        """Stop all live-updating scanners in this channel."""
        channel_id = ctx.channel.id
        if channel_id not in self.channel_states or not self.channel_states[channel_id]:
            await ctx.message.add_reaction("⚠️")
            await ctx.send("❌ VWAP scanner tidak sedang berjalan di channel ini!")
            return

        try:
            intervals_to_stop = list(self.channel_states[channel_id].keys())
            for interval in intervals_to_stop:
                interval_str = format_interval(interval)
                state = self.channel_states[channel_id][interval]
                state['running'] = False
                if state.get('task'):
                    state['task'].cancel()

                try:
                    embed = discord.Embed(
                        title=f"VWAP Scanner [{interval_str}]",
                        description="🛑 VWAP scanner telah dihentikan",
                        color=discord.Color.red()
                    )
                    await state['message'].edit(embed=embed, attachments=[])
                except Exception:
                    pass

            del self.channel_states[channel_id]
            remove_channel_state(channel_id)
            await ctx.message.add_reaction("✅")
            await ctx.send(f"⏹️ VWAP scanner dihentikan ({len(intervals_to_stop)} tabel).")

        except Exception as e:
            logger.error(f"Error in stop_command: {e}")
            await ctx.send(f"❌ Error stopping scanner: {str(e)[:100]}")

    @commands.command(name="session")
    async def session_command(self, ctx):
        """View active trading session, upcoming sessions, and trigger refresh."""
        try:
            current_session, weight = detect_session()
            next_session_name, next_session_time = get_next_session_info()
            current_flag = get_session_flag(current_session)
            next_flag = get_session_flag(next_session_name)
            monitor_status = "✅ Running" if (self.session_check_task and not self.session_check_task.done()) else "❌ Inactive"

            embed = discord.Embed(
                title="📊 Trading Session Status",
                description=(
                    f"**Current Session:** {current_session} {current_flag}\n"
                    f"**Session Weight:** `{weight}x`\n"
                    f"**Next Session:** {next_session_name} {next_flag} at `{next_session_time}`\n"
                    f"**Monitoring Task:** {monitor_status}\n"
                    f"**Tracked Session:** {self.current_session}"
                ),
                color=discord.Color.blue()
            )

            active_count = sum(len(ivs) for ivs in self.channel_states.values())
            embed.add_field(name="Active Scanners", value=f"{active_count} scanner(s) running across all channels", inline=False)
            await ctx.send(embed=embed)

            if active_count > 0:
                await ctx.send("🔄 Memperbarui semua tabel scanner aktif...")
                await self.trigger_all_updates()
                await ctx.send("✅ Tabel berhasil diperbarui!")

        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @commands.command(name="health")
    async def health_command(self, ctx):
        """Inspect health status of all live VWAP scanners."""
        try:
            embed = discord.Embed(
                title="🏥 VWAP Scanner Health Status",
                description="Status kesehatan dan interval pembaruan seluruh scanner aktif",
                color=discord.Color.green()
            )

            if not self.channel_states:
                embed.add_field(name="Status", value="❌ Tidak ada scanner yang sedang berjalan saat ini.", inline=False)
                await ctx.send(embed=embed)
                return

            total_scanners = 0
            healthy_scanners = 0

            for channel_id, intervals in self.channel_states.items():
                channel = self.bot.get_channel(channel_id)
                ch_name = f"#{channel.name}" if channel else f"Channel ID {channel_id}"

                lines = []
                for interval, state in intervals.items():
                    total_scanners += 1
                    interval_str = format_interval(interval)
                    last_update = state.get('last_scheduled_update')
                    if last_update:
                        diff_sec = (datetime.now() - last_update).total_seconds()
                        if diff_sec < interval * 1.5:
                            status = "🟢 Healthy"
                            healthy_scanners += 1
                        elif diff_sec < interval * 3:
                            status = "🟡 Delayed"
                        else:
                            status = "🔴 Stale"
                        lines.append(f"• `{interval_str}`: {status} ({int(diff_sec)}s lalu)")
                    else:
                        lines.append(f"• `{interval_str}`: ⚪ Initializing")

                embed.add_field(name=f"📺 {ch_name}", value="\n".join(lines), inline=False)

            summary = f"Total: {total_scanners} scanner | Sehat: {healthy_scanners}/{total_scanners}"
            embed.set_footer(text=summary)
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Error checking health: {e}")
