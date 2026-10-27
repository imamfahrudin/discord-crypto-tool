"""
Screening Cog for discord-crypto-tool.
Encapsulates real-time signals, multi-coin scanning, scalp analysis, coin list, ping, and /help.
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import concurrent.futures
import time
import os
import requests
import traceback
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

from config import (
    BOT_TITLE_PREFIX,
    BOT_FOOTER_NAME,
    SIGNAL_CONCURRENCY,
    OHLC_LIMIT
)
from core.utils import format_price_dynamic, release_memory
from .exchange_factory import normalize_symbol, pair_exists, get_all_pairs
from .signal_logic import generate_trade_plan
from .chart_generator import generate_chart_with_setup, generate_neutral_chart
from .views import CoinListView

LOG_PREFIX = "[screening_cog]"


def get_coin_image_url(symbol: str) -> str:
    """Get coin logo thumbnail from CoinGecko API."""
    try:
        coin_symbol = symbol.replace('USDT', '').replace('_USDT', '').lower()
        url = f"https://api.coingecko.com/api/v3/search?query={coin_symbol}"
        response = requests.get(url, timeout=4)
        if response.status_code == 200:
            data = response.json()
            if data.get('coins') and len(data['coins']) > 0:
                coin = data['coins'][0]
                return coin.get('large', coin.get('thumb', ''))
    except Exception:
        pass
    return ""


class ScreeningCog(commands.Cog):
    """Cog handling crypto screening commands and interactive signals."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.semaphore = asyncio.Semaphore(SIGNAL_CONCURRENCY)

    async def on_bot_ready(self):
        """Warm up pair cache upon bot ready in background."""
        logger_name = f"{LOG_PREFIX}"
        try:
            print(f"{logger_name} ⏳ Loading initial exchange pair caches in background...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, lambda: get_all_pairs('bybit', force_refresh=True))
            print(f"{logger_name} ✅ Bybit pair cache initialized.")
        except Exception as e:
            print(f"{logger_name} ⚠️ Non-critical pair cache error: {e}")

    # -----------------------------------------------------------------------
    # Message / Response Helpers
    # -----------------------------------------------------------------------
    async def send_response(self, ctx_or_message, **kwargs):
        """Send reply with fallback handling."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await ctx_or_message.reply(**kwargs)
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                # If error was caused by file attachment, retry text-only
                if 'file' in kwargs:
                    kwargs_no_file = {k: v for k, v in kwargs.items() if k != 'file'}
                    try:
                        await ctx_or_message.reply(**kwargs_no_file)
                        return
                    except Exception:
                        pass
                raise e

    async def send_error(self, ctx_or_message, message: str):
        """Send formatted error message with sad reaction."""
        try:
            await ctx_or_message.reply(message)
        except Exception:
            pass

        msg_obj = ctx_or_message.message if hasattr(ctx_or_message, 'message') else ctx_or_message
        try:
            await msg_obj.remove_reaction('🫡', msg_obj.guild.me)
            await msg_obj.add_reaction('😢')
        except Exception:
            pass

    def generate_chart_from_data(self, data: dict, symbol: str, timeframe: str, exchange: str = 'bybit'):
        """Generate chart BytesIO with setup markers."""
        try:
            direction = data.get('direction', 'neutral').lower()
            if direction == 'neutral':
                chart_buf = generate_neutral_chart(
                    df=data['df'],
                    symbol=symbol,
                    timeframe=timeframe,
                    ema13=data.get('ema13_series'),
                    ema21=data.get('ema21_series'),
                    current_price=data.get('current_price'),
                    ema_short=data.get('ema_short', 13),
                    ema_long=data.get('ema_long', 21),
                    exchange=exchange
                )
            else:
                chart_buf = generate_chart_with_setup(
                    df=data['df'],
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction,
                    entry_price=data.get('entry'),
                    stop_loss=data.get('stop_loss'),
                    tp1=data.get('tp1'),
                    tp2=data.get('tp2'),
                    ema13=data.get('ema13_series'),
                    ema21=data.get('ema21_series'),
                    fvg_zones=data.get('fvg_zones'),
                    ob_high=data.get('ob_high'),
                    ob_low=data.get('ob_low'),
                    current_price=data.get('current_price'),
                    ema_short=data.get('ema_short', 13),
                    ema_long=data.get('ema_long', 21),
                    exchange=exchange,
                    confidence=data.get('confidence')
                )
            release_memory()
            return chart_buf
        except Exception as e:
            print(f"{LOG_PREFIX} ❌ Chart generation error: {e}")
            release_memory()
            return None

    def create_signal_embed(self, data: dict, symbol: str, timeframe: str, show_detail: bool = False,
                            exchange: str = 'bybit', original_ema_short: int = 13, original_ema_long: int = 21,
                            direction: str = None, user_id: int = None):
        """Construct embed and interactive view for a single signal."""
        original_ema_short = original_ema_short or 13
        original_ema_long = original_ema_long or 21
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        wib_time = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime('%Y-%m-%d %H:%M:%S WIB')

        direction_val = data.get('direction', 'NETRAL').upper()
        if direction_val == "LONG":
            color = 0x00FF88; emoji = "🟢"
        elif direction_val == "SHORT":
            color = 0xFF5555; emoji = "🔴"
        else:
            color = 0xFFD700; emoji = "🟡"

        interval_map = {
            "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "2h": "120", "4h": "240", "6h": "360",
            "1d": "1D", "1w": "1W", "1M": "1M"
        }
        interval = interval_map.get(timeframe.lower(), "1D")
        exchange_upper = exchange.upper()
        pair_symbol = symbol if symbol.endswith('USDT') else f"{symbol}USDT"
        tv_url = f"https://www.tradingview.com/chart/?symbol={quote(f'{exchange_upper}:{pair_symbol}.P')}&interval={interval}"

        embed = discord.Embed(color=color)
        coin_image_url = get_coin_image_url(symbol)
        if coin_image_url:
            embed.set_thumbnail(url=coin_image_url)

        if direction_val == "NETRAL":
            embed.title = f"{BOT_TITLE_PREFIX}"
            embed.description = "📊 **Analysis:** Market is consolidating or FVG/Momentum criteria not met."
            embed.add_field(name="🕒 Timeframe", value=f"`{timeframe.upper()}`", inline=True)
            embed.add_field(name="🧭 Generated", value=f"`{current_time}`", inline=True)
            embed.add_field(name="📈 EMA Periods", value=f"`{data.get('ema_short', 13)}/{data.get('ema_long', 21)}`", inline=True)
            embed.add_field(name="🏦 Exchange", value=f"`{exchange_upper}`", inline=True)
            if show_detail:
                embed.add_field(name="📋 Detailed Analysis", value=data.get('insight', 'No details available.'), inline=False)
        else:
            entry_fmt = format_price_dynamic(data.get('entry'))
            sl_fmt = format_price_dynamic(data.get('stop_loss'))
            tp1_fmt = format_price_dynamic(data.get('tp1'))
            tp2_fmt = format_price_dynamic(data.get('tp2'))
            rr_fmt = f"{data.get('rr'):.2f}R" if data.get('rr') else "N/A"
            confidence = f"{data.get('confidence')}% {data.get('confidence_level', '')}"

            entry = data.get('entry')
            sl = data.get('stop_loss')
            tp1 = data.get('tp1')
            tp2 = data.get('tp2')

            sl_pct = ((sl - entry) / entry) * 100 if entry and entry != 0 else 0
            tp1_pct = ((tp1 - entry) / entry) * 100 if entry and entry != 0 else 0
            tp2_pct = ((tp2 - entry) / entry) * 100 if entry and entry != 0 else 0

            embed.title = f"{BOT_TITLE_PREFIX}"
            embed.description = f"{emoji} **{direction_val} Signal** for {symbol} on {timeframe.upper()} timeframe"
            embed.add_field(name="📊 Pair", value=f"`{symbol}`", inline=True)
            embed.add_field(name="🕒 Timeframe", value=f"`{timeframe.upper()}`", inline=True)
            embed.add_field(name="🧭 Generated", value=f"`{current_time}`", inline=True)
            embed.add_field(name="📈 EMA Periods", value=f"`{data.get('ema_short', 13)}/{data.get('ema_long', 21)}`", inline=True)
            embed.add_field(name="🏦 Exchange", value=f"`{exchange_upper}`", inline=True)
            embed.add_field(name="💰 Risk/Reward", value=f"`{rr_fmt}`", inline=True)
            embed.add_field(name="📈 Entry", value=f"```{entry_fmt}```", inline=True)
            embed.add_field(name=f"🛑 Stop Loss ({sl_pct:+.2f}%)", value=f"```{sl_fmt}```", inline=True)
            embed.add_field(
                name="🎯 Take Profits",
                value=f"**TP1 (1.5R) ({tp1_pct:+.2f}%):** ```{tp1_fmt}```\n**TP2 (Final) ({tp2_pct:+.2f}%):** ```{tp2_fmt}```",
                inline=False
            )
            embed.add_field(name="💡 Confidence", value=f"`{confidence}`", inline=True)
            if show_detail:
                embed.add_field(name="📋 Detailed Analysis", value=data.get('insight', 'No details available.'), inline=False)

        embed.set_footer(text=f"{BOT_FOOTER_NAME} • Time: {wib_time}")
        embed.set_image(url=f"attachment://chart_{symbol}.png")

        # Interactive View
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            style=discord.ButtonStyle.link,
            label="📈 View on TradingView",
            url=tv_url,
            emoji="📊"
        ))

        current_short = data.get('ema_short', 13)
        current_long = data.get('ema_long', 21)
        if current_short == 25 and current_long == 50:
            target_short, target_long = (13, 21) if (original_ema_short == 25 and original_ema_long == 50) else (original_ema_short, original_ema_long)
            label = f"Switch to EMA {target_short}/{target_long}"
        else:
            target_short, target_long = 25, 50
            label = "Switch to EMA 25/50"

        view.add_item(discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label=label,
            custom_id=f"ema_switch:{symbol.replace('USDT', '')}:{timeframe}:{direction or 'None'}:{exchange}:{current_short}:{current_long}:{target_short}:{target_long}:{original_ema_short}:{original_ema_long}:{show_detail}:{user_id or 0}"
        ))

        return embed, view

    def create_scan_embed(self, data: dict, symbol: str, timeframe: str, all_results: list, exchange: str = 'bybit',
                          original_ema_short: int = 13, original_ema_long: int = 21, direction: str = None,
                          user_id: int = None, scan_type: str = "Scanned"):
        """Construct embed for scan/scalp multi-setup result."""
        embed, view = self.create_signal_embed(
            data, symbol, timeframe, False, exchange, original_ema_short, original_ema_long, direction, user_id
        )

        direction_val = data.get('direction', 'NETRAL').upper()
        if direction_val != "NETRAL":
            embed.description = f"**{direction_val} Signal** for {symbol} on {timeframe.upper()} (Best from {scan_type.lower()})"

        # List all tested setups and confidence
        sorted_results = sorted(all_results, key=lambda x: x[0], reverse=True)
        conf_lines = []
        for i, (conf, setup, _) in enumerate(sorted_results):
            if i == 0:
                conf_lines.append(f"• {conf}% - `{setup}` ✅")
            else:
                conf_lines.append(f"• {conf}% - `{setup}`")
        embed.add_field(name=f"📋 All Confidences ({scan_type} Setups)", value="\n".join(conf_lines), inline=False)
        return embed, view

    async def scan_single_coin(self, coin: str, ema_short: int, ema_long: int, exchange: str):
        """Helper to scan multiple timeframes for a single coin."""
        setups = [("1h", "long"), ("1h", "short"), ("4h", "long"), ("4h", "short")]
        results = []
        for tf, direction in setups:
            def run():
                norm = normalize_symbol(coin, exchange)
                if not pair_exists(norm, exchange):
                    return None
                return generate_trade_plan(norm, tf, exchange, forced_direction=direction, return_dict=True, ema_short=ema_short, ema_long=ema_long)

            try:
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(self.executor, run)
                if res and not isinstance(res, str):
                    setup_str = f"${coin} {tf} {direction}"
                    results.append((res.get('confidence', 0), setup_str, res))
            except Exception:
                continue

        if not results:
            return None, None, []
        best = max(results, key=lambda x: x[0])
        best_conf, best_setup, best_data = best
        best_tf = best_setup.split()[1]
        return best_data, best_tf, results

    # -----------------------------------------------------------------------
    # Signal Pipeline Execution
    # -----------------------------------------------------------------------
    async def process_signal(self, ctx_or_message, symbol: str, timeframe: str = "1h", direction: str = None,
                             exchange: str = "bybit", ema_short: int = None, ema_long: int = None, show_detail: bool = False):
        """Execute full signal generation with concurrency limits."""
        async with self.semaphore:
            valid_tfs = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','1d','1w','1M']
            if timeframe.lower() not in [t.lower() for t in valid_tfs]:
                await self.send_error(ctx_or_message, f"⚠️ Invalid timeframe `{timeframe}`. Pilihan: {valid_tfs}.")
                return

            forced = direction.strip().lower() if direction else None
            if forced and forced not in ('long', 'short'):
                await self.send_error(ctx_or_message, "⚠️ Direction harus `long` atau `short`.")
                return

            def blocking_plan():
                symbol_norm = normalize_symbol(symbol, exchange)
                if not pair_exists(symbol_norm, exchange):
                    return f"❌ Pasangan `{symbol_norm}` tidak tersedia di {exchange.upper()}."
                return generate_trade_plan(
                    symbol_norm, timeframe, exchange,
                    forced_direction=forced,
                    return_dict=True,
                    ema_short=ema_short or 13,
                    ema_long=ema_long or 21
                )

            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(self.executor, blocking_plan)
                if isinstance(result, str):
                    await self.send_error(ctx_or_message, result)
                    return

                symbol_norm = normalize_symbol(symbol, exchange)
                chart_buf = await loop.run_in_executor(
                    self.executor, self.generate_chart_from_data, result, symbol_norm, timeframe, exchange
                )

                user_id = ctx_or_message.author.id if hasattr(ctx_or_message, 'author') else ctx_or_message.user.id
                embed, view = self.create_signal_embed(
                    result, symbol_norm, timeframe, show_detail, exchange, ema_short, ema_long, direction, user_id
                )

                if chart_buf:
                    file = discord.File(chart_buf, filename=f"chart_{symbol_norm}.png")
                    await self.send_response(ctx_or_message, embed=embed, file=file, view=view)
                else:
                    await self.send_response(ctx_or_message, embed=embed, view=view)

                msg_obj = ctx_or_message.message if hasattr(ctx_or_message, 'message') else ctx_or_message
                try:
                    await msg_obj.remove_reaction('🫡', msg_obj.guild.me)
                    await msg_obj.add_reaction('✅')
                except Exception:
                    pass

            except Exception as e:
                print(f"{LOG_PREFIX} ❌ Error in process_signal: {e}")
                traceback.print_exc()
                await self.send_error(ctx_or_message, f"⚠️ Error menghasilkan sinyal: `{e}`")

    # -----------------------------------------------------------------------
    # Quick Signal ($BTC, $ETH 4h long, etc.)
    # -----------------------------------------------------------------------
    async def handle_quick_signal(self, message: discord.Message):
        """Parse and run $ quick command."""
        content = message.content[1:].strip()
        if not content:
            return

        parts = content.split()
        first_part = parts[0].lower()
        if first_part in ('scan', 'signal', 'coinlist', 'help', 'start', 'stop', 'session', 'health', 'forex'):
            await self.send_error(
                message,
                f"⚠️ Perintah `${first_part}` tidak menggunakan prefix `$`. Gunakan `!{first_part}` atau `/help`."
            )
            return

        symbol = parts[0].upper()
        remaining = parts[1:]

        timeframe = None
        direction = None
        emas = []
        show_detail = False
        exchange = "bybit"
        valid_tfs = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','1d','1w','1M']

        for part in remaining:
            pl = part.lower()
            if pl in ('binance', 'bybit', 'bitget', 'gateio', 'gate'):
                exchange = 'gateio' if pl == 'gate' else pl
                continue
            if pl in valid_tfs:
                timeframe = pl
                continue
            if pl in ('long', 'short'):
                direction = pl
                continue
            if pl == 'detail':
                show_detail = True
                continue
            # Try parse EMA
            ema_str = pl.replace('ema', '') if pl.startswith('ema') else pl
            try:
                emas.append(int(ema_str))
            except ValueError:
                await self.send_error(message, f"⚠️ Parameter tidak valid: `{part}`.")
                return

        timeframe = timeframe or "1h"
        ema_short = emas[0] if len(emas) >= 2 else (emas[0] if len(emas) == 1 else None)
        ema_long = emas[1] if len(emas) >= 2 else None

        await self.process_signal(
            message, symbol, timeframe, direction, exchange, ema_short, ema_long, show_detail
        )

    # -----------------------------------------------------------------------
    # Discord Prefix Commands
    # -----------------------------------------------------------------------
    @commands.command(name="signal")
    async def signal_command(self, ctx, *args):
        """
        Usage: !signal <symbol> [timeframe] [direction] [ema_short] [ema_long] [exchange] [detail]
        """
        if len(args) < 1:
            await self.send_error(
                ctx,
                "⚠️ Format: `!signal SYMBOL [TIMEFRAME] [long/short] [ema_short] [ema_long] [binance] [detail]`\nContoh: `!signal BTC` atau `!signal ETH 4h long ema20 ema50`"
            )
            return

        symbol = args[0].upper()
        remaining = list(args[1:])

        timeframe = None
        direction = None
        emas = []
        show_detail = False
        exchange = "bybit"
        valid_tfs = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','1d','1w','1M']

        for part in remaining:
            pl = part.lower()
            if pl in ('binance', 'bybit', 'bitget', 'gateio', 'gate'):
                exchange = 'gateio' if pl == 'gate' else pl
                continue
            if pl in valid_tfs:
                timeframe = pl
                continue
            if pl in ('long', 'short'):
                direction = pl
                continue
            if pl == 'detail':
                show_detail = True
                continue
            ema_str = pl.replace('ema', '') if pl.startswith('ema') else pl
            try:
                emas.append(int(ema_str))
            except ValueError:
                await self.send_error(ctx, f"⚠️ Parameter tidak valid: `{part}`.")
                return

        timeframe = timeframe or "1h"
        ema_short = emas[0] if len(emas) >= 2 else None
        ema_long = emas[1] if len(emas) >= 2 else None

        await self.process_signal(
            ctx, symbol, timeframe, direction, exchange, ema_short, ema_long, show_detail
        )

    @commands.command(name="scan")
    async def scan_command(self, ctx, *, args: str):
        """Scan multiple coins for highest confidence setup (max 5 coins)."""
        if not args.strip():
            await self.send_error(ctx, "⚠️ Format: `!scan COIN1 COIN2 ... [ema_short] [ema_long] [binance]`")
            return

        parts = args.split()
        coins = []
        emas = []
        exchange = "bybit"

        for p in parts:
            pl = p.lower()
            if pl in ('binance', 'bybit', 'bitget', 'gateio', 'gate'):
                exchange = 'gateio' if pl == 'gate' else pl
                continue
            ema_str = pl.replace('ema', '') if pl.startswith('ema') else pl
            try:
                emas.append(int(ema_str))
            except ValueError:
                coins.append(p.strip().upper())

        coin_list = []
        for c in coins:
            coin_list.extend([x.strip() for x in c.split(',') if x.strip()])
        coins_final = [c for c in coin_list if c][:5]

        if not coins_final:
            await self.send_error(ctx, "⚠️ Tidak ada coin valid yang diberikan.")
            return

        ema_short = emas[0] if len(emas) >= 2 else 13
        ema_long = emas[1] if len(emas) >= 2 else 21

        setups = [("1h", "long"), ("1h", "short"), ("4h", "long"), ("4h", "short")]
        loop = asyncio.get_running_loop()

        for coin in coins_final:
            best_data, best_tf, all_results = await self.scan_single_coin(coin, ema_short, ema_long, exchange)
            if not best_data:
                await self.send_error(ctx, f"⚠️ Tidak ada hasil valid untuk {coin}.")
                continue

            symbol_norm = normalize_symbol(coin, exchange)
            chart_buf = await loop.run_in_executor(
                self.executor, self.generate_chart_from_data, best_data, symbol_norm, best_tf, exchange
            )

            embed, view = self.create_scan_embed(
                best_data, symbol_norm, best_tf, all_results, exchange, ema_short, ema_long, None, ctx.author.id, "Scanned"
            )

            if chart_buf:
                file = discord.File(chart_buf, filename=f"chart_{symbol_norm}.png")
                await self.send_response(ctx, embed=embed, file=file, view=view)
            else:
                await self.send_response(ctx, embed=embed, view=view)

    @commands.command(name="scalp")
    async def scalp_command(self, ctx, *, args: str):
        """Scalp multiple coins on short timeframes (15m, 30m)."""
        if not args.strip():
            await self.send_error(ctx, "⚠️ Format: `!scalp COIN1 COIN2 ... [ema_short] [ema_long] [binance]`")
            return

        parts = args.split()
        coins = []
        emas = []
        exchange = "bybit"

        for p in parts:
            pl = p.lower()
            if pl in ('binance', 'bybit', 'bitget', 'gateio', 'gate'):
                exchange = 'gateio' if pl == 'gate' else pl
                continue
            ema_str = pl.replace('ema', '') if pl.startswith('ema') else pl
            try:
                emas.append(int(ema_str))
            except ValueError:
                coins.append(p.strip().upper())

        coin_list = []
        for c in coins:
            coin_list.extend([x.strip() for x in c.split(',') if x.strip()])
        coins_final = [c for c in coin_list if c][:5]

        if not coins_final:
            await self.send_error(ctx, "⚠️ Tidak ada coin valid yang diberikan.")
            return

        ema_short = emas[0] if len(emas) >= 2 else 13
        ema_long = emas[1] if len(emas) >= 2 else 21

        setups = [("15m", "long"), ("15m", "short"), ("30m", "long"), ("30m", "short")]
        loop = asyncio.get_running_loop()

        for coin in coins_final:
            results = []
            for tf, direction in setups:
                def run():
                    norm = normalize_symbol(coin, exchange)
                    if not pair_exists(norm, exchange):
                        return None
                    return generate_trade_plan(norm, tf, exchange, forced_direction=direction, return_dict=True, ema_short=ema_short, ema_long=ema_long)

                try:
                    res = await loop.run_in_executor(self.executor, run)
                    if res and not isinstance(res, str):
                        setup_str = f"${coin} {tf} {direction}"
                        results.append((res.get('confidence', 0), setup_str, res))
                except Exception:
                    continue

            if not results:
                await self.send_error(ctx, f"⚠️ Tidak ada hasil valid untuk {coin}.")
                continue

            best = max(results, key=lambda x: x[0])
            best_conf, best_setup, best_data = best
            best_tf = best_setup.split()[1]

            symbol_norm = normalize_symbol(coin, exchange)
            chart_buf = await loop.run_in_executor(
                self.executor, self.generate_chart_from_data, best_data, symbol_norm, best_tf, exchange
            )

            embed, view = self.create_scan_embed(
                best_data, symbol_norm, best_tf, results, exchange, ema_short, ema_long, None, ctx.author.id, "Scalped"
            )

            if chart_buf:
                file = discord.File(chart_buf, filename=f"chart_{symbol_norm}.png")
                await self.send_response(ctx, embed=embed, file=file, view=view)
            else:
                await self.send_response(ctx, embed=embed, view=view)

    @commands.command(name="coinlist")
    async def coinlist_command(self, ctx, *, args: str = ""):
        """List all available trading pairs with pagination."""
        args_lower = args.lower()
        if 'binance' in args_lower:
            exchange = 'binance'
        elif 'bitget' in args_lower:
            exchange = 'bitget'
        elif 'gateio' in args_lower or 'gate' in args_lower:
            exchange = 'gateio'
        else:
            exchange = 'bybit'

        loop = asyncio.get_running_loop()
        def fetch_coins():
            pairs = get_all_pairs(exchange=exchange, force_refresh=False)
            coins = set()
            for pair in pairs:
                base = pair.replace('USDT', '').replace('USDC', '').replace('_USDT', '')
                if base and base != pair:
                    coins.add(base.upper())
            return sorted(coins)

        try:
            coins = await loop.run_in_executor(self.executor, fetch_coins)
            if not coins:
                await self.send_error(ctx, f"⚠️ Tidak ada koin yang ditemukan untuk {exchange.upper()}.")
                return

            chunk_size = 100
            chunks = [coins[i:i + chunk_size] for i in range(0, len(coins), chunk_size)]
            view = CoinListView(chunks, len(coins), exchange=exchange)
            embed = view.get_embed()
            await self.send_response(ctx, embed=embed, view=view)
        except Exception as e:
            await self.send_error(ctx, f"⚠️ Error mengambil coin list: {e}")

    @commands.command(name="ping")
    async def ping_command(self, ctx):
        """Check bot latency and exchange benchmarks for $BTC."""
        bot_latency = round(self.bot.latency * 1000)
        exchanges = ['bybit', 'binance', 'bitget', 'gateio']
        benchmark_results = {}
        loop = asyncio.get_running_loop()

        async def bench(ex):
            start = time.time()
            try:
                coro = loop.run_in_executor(
                    self.executor,
                    lambda: generate_trade_plan("BTC", "1h", ex, forced_direction=None, return_dict=True, ema_short=13, ema_long=21)
                )
                res = await asyncio.wait_for(coro, timeout=15)
                if isinstance(res, str):
                    return ex, "Error"
                return ex, f"{round((time.time() - start) * 1000)} ms"
            except Exception:
                return ex, "Timeout"

        tasks = [asyncio.create_task(bench(ex)) for ex in exchanges]
        results = await asyncio.gather(*tasks)
        for ex, val in results:
            benchmark_results[ex] = val

        embed = discord.Embed(
            title="🏓 Bot Ping & Exchange Benchmark",
            description="Measuring bot response time and exchange signal generation speed for $BTC",
            color=0x00FF88
        )
        embed.add_field(name="🤖 Bot Latency", value=f"`{bot_latency} ms`", inline=False)
        for ex, t in benchmark_results.items():
            embed.add_field(name=f"🏦 {ex.upper()}", value=f"`{t}`", inline=True)
        embed.set_footer(text=f"{BOT_FOOTER_NAME}")
        await ctx.reply(embed=embed)

    # -----------------------------------------------------------------------
    # Interactive Button Listener
    # -----------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle dynamic EMA switch buttons."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = interaction.data.get('custom_id', '')
        if not custom_id.startswith("ema_switch:"):
            return

        parts = custom_id.split(":")
        if len(parts) != 13:
            await interaction.response.send_message("Invalid button data.", ephemeral=True)
            return

        _, symbol, timeframe, direction, exchange, c_short, c_long, t_short, t_long, orig_short, orig_long, show_detail, user_id_str = parts
        c_short, c_long, t_short, t_long = int(c_short), int(c_long), int(t_short), int(t_long)
        orig_short, orig_long = int(orig_short), int(orig_long)
        show_detail = (show_detail == "True")
        direction = None if direction == "None" else direction
        user_id = int(user_id_str) if user_id_str != "0" else None

        if user_id and user_id != interaction.user.id:
            await interaction.response.send_message("Kamu hanya bisa menggunakan tombol ini pada sinyal yang kamu minta.", ephemeral=True)
            return

        await interaction.response.defer()

        loop = asyncio.get_running_loop()
        def run_regen():
            norm = normalize_symbol(symbol, exchange)
            if not pair_exists(norm, exchange):
                return f"❌ Pasangan `{norm}` tidak tersedia di {exchange.upper()}."
            return generate_trade_plan(norm, timeframe, exchange, forced_direction=direction, return_dict=True, ema_short=t_short, ema_long=t_long)

        try:
            result = await loop.run_in_executor(self.executor, run_regen)
            if isinstance(result, str):
                await interaction.followup.send(result, ephemeral=True)
                return

            symbol_norm = normalize_symbol(symbol, exchange)
            chart_buf = await loop.run_in_executor(
                self.executor, self.generate_chart_from_data, result, symbol_norm, timeframe, exchange
            )

            is_scan = "(Scanned)" in interaction.message.embeds[0].title if interaction.message.embeds else False
            if is_scan:
                best_data, best_tf, all_res = await self.scan_single_coin(symbol, t_short, t_long, exchange)
                if not best_data:
                    await interaction.followup.send("Could not generate scan setup.", ephemeral=True)
                    return
                chart_buf = await loop.run_in_executor(
                    self.executor, self.generate_chart_from_data, best_data, symbol_norm, best_tf, exchange
                )
                embed, view = self.create_scan_embed(best_data, symbol_norm, best_tf, all_res, exchange, orig_short, orig_long, direction, user_id)
            else:
                embed, view = self.create_signal_embed(result, symbol_norm, timeframe, show_detail, exchange, orig_short, orig_long, direction, user_id)

            if chart_buf:
                file = discord.File(chart_buf, filename=f"chart_{symbol_norm}.png")
                await interaction.message.edit(embed=embed, attachments=[file], view=view)
            else:
                await interaction.message.edit(embed=embed, attachments=[], view=view)
        except Exception as e:
            await interaction.followup.send(f"Error updating signal: {e}", ephemeral=True)

    # -----------------------------------------------------------------------
    # Slash Command: /help
    # -----------------------------------------------------------------------
    @app_commands.command(name="help", description="Tampilkan panduan lengkap perintah Crypto Tool")
    async def slash_help(self, interaction: discord.Interaction):
        """Unified complete help command for all features."""
        embed = discord.Embed(
            title="🤖💎 **CRYPTO TOOL — PANDUAN LENGKAP**",
            description="Platform Bot Terpadu untuk **Signal Screening**, **VWAP**, **Forex**, dan **Degen token lookup**!",
            color=0x00FF88
        )

        embed.add_field(
            name="📊 **Perintah Sinyal Trading (Screening)**",
            value=(
                "🔹 **`$COIN [timeframe] [long/short] [exchange]`** — Sinyal cepat (contoh: `$BTC` atau `$ETH 4h long`)\n"
                "🔹 **`!signal {coin} [timeframe] [direction] [ema_short] [ema_long] [exchange]`** — Sinyal kustom\n"
                "🔹 **`!scan {coin1,coin2,...} [ema_short] [ema_long]`** — Scan multi-koin (max 5) untuk setup terbaik\n"
                "🔹 **`!scalp {coin1,coin2,...}`** — Scalping koin pada timeframe 15m & 30m\n"
                "🔹 **`!coinlist [exchange]`** — Daftar koin yang tersedia (Bybit, Binance, Bitget, Gate.io)\n"
                "🔹 **`!ping`** — Cek latensi bot dan benchmark respons API exchange"
            ),
            inline=False
        )

        embed.add_field(
            name="🌊 **Perintah VWAP Scanner (Live Table)**",
            value=(
                "🔹 **`!start vwap`** — Mulai live-updating tabel VWAP di channel ini sesuai interval config\n"
                "🔹 **`!stop vwap`**  — Hentikan live-updating scanner di channel ini\n"
                "🔹 **`!session`**   — Cek sesi trading aktif (Sydney, Tokyo, London, New York) & trigger manual refresh\n"
                "🔹 **`!health`**    — Pantau status kesehatan dan update interval semua scanner aktif"
            ),
            inline=False
        )

        embed.add_field(
            name="📰 **Perintah Forex Factory Notifier**",
            value=(
                "🔹 **`!start forex`** — Mulai notifier kalender ekonomi Forex Factory di channel ini\n"
                "🔹 **`!stop forex`**  — Hentikan notifier Forex Factory di channel ini"
            ),
            inline=False
        )

        embed.add_field(
            name="🧪 **Degen Token Lookup**",
            value=(
                "🔹 **Tempel contract address** — Balasan otomatis data DexScreener + chart (tanpa prefix)\n"
                "🔹 Contoh EVM: `0x` + 40 hex. Contoh Solana: alamat base58 32–44 karakter\n"
                "🔹 Tombol **Check Current Price**, **Refresh Price**, dan **Delete** ada di balasan itu\n"
                "🔹 `$` dan `!` tetap milik Screening, VWAP, dan Forex — tidak dipindai sebagai contract"
            ),
            inline=False
        )

        embed.add_field(
            name="⏰ **Timeframe yang Didukung**",
            value="`1m` `3m` `5m` `15m` `30m` `1h` `2h` `4h` `6h` `1d` `1w`",
            inline=True
        )

        embed.add_field(
            name="🏦 **Exchange yang Didukung**",
            value="`bybit` (default) • `binance` • `bitget` • `gateio`",
            inline=True
        )

        embed.add_field(
            name="💡 **Contoh Cepat**",
            value=(
                "• `$BTC` → Sinyal Bybit 1h\n"
                "• `$SOL 4h long binance` → Sinyal Long Binance 4h\n"
                "• `!scan BTC ETH SOL` → Scan 3 koin terbaik\n"
                "• `!start vwap` → Jalankan tabel VWAP real-time di channel\n"
                "• `!start forex` → Aktifkan notifikasi Forex Factory harian\n"
                "• `0xabc...` → Lookup token degen (DexScreener + chart)"
            ),
            inline=False
        )

        embed.set_footer(text=f"{BOT_FOOTER_NAME}")
        await interaction.response.send_message(embed=embed)
