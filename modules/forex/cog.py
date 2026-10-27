"""
Forex Cog for discord-crypto-tool.
Manages per-channel Forex Factory economic calendar notifications.

Commands (routed via the central dispatcher):
    !start forex  — start daily Forex Factory alerts in this channel
    !stop forex   — stop Forex Factory alerts in this channel
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, time as dt_time

import discord
from discord.ext import commands

import pytz

from config import (
    FOREX_TIMEZONE,
    FOREX_SCHEDULE_HOUR,
    FOREX_SCHEDULE_MINUTE,
)
from .fetcher import fetch_all_news, build_embed_dict

logger = logging.getLogger("crypto_tool.forex.cog")


class ForexCog(commands.Cog):
    """
    Cog that posts Forex Factory economic calendar embeds to Discord channels.

    Per-channel state is kept in ``self.channel_states``:
        channel_id (int) → {
            'running': bool,
            'task':    asyncio.Task | None,
        }

    No shared global state — stopping one channel never touches another.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # channel_id -> {'running': bool, 'task': Task | None}
        self.channel_states: dict[int, dict] = {}

    def cog_unload(self):
        """Cancel all background tasks when the cog is unloaded."""
        for cid, state in list(self.channel_states.items()):
            self._cancel_channel(cid)

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _cancel_channel(self, channel_id: int):
        """Cancel the background task for a channel and clean up state."""
        state = self.channel_states.get(channel_id)
        if not state:
            return
        state["running"] = False
        task = state.get("task")
        if task and not task.done():
            task.cancel()
        self.channel_states.pop(channel_id, None)

    async def _post_forex_update(self, channel: discord.TextChannel) -> bool:
        """
        Fetch latest Forex Factory data and post it to *channel*.
        Returns True on success, False on failure.
        """
        try:
            loop = asyncio.get_running_loop()
            events_data = await loop.run_in_executor(None, fetch_all_news)
            embed_dict = build_embed_dict(events_data)

            if embed_dict is None:
                await channel.send(
                    "📭 **Forex Notifier:** No matching events found for today/this week."
                )
                return True

            embed = discord.Embed.from_dict(embed_dict)
            await channel.send(embed=embed)
            return True

        except Exception as exc:
            logger.error(f"Failed to post forex update to #{channel.name}: {exc}\n{traceback.format_exc()}")
            return False

    async def _scheduler_loop(self, channel_id: int):
        """
        Background task that:
          1. Posts an immediate update on start.
          2. Waits until the next configured daily time and re-posts every day.
        """
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            logger.error(f"Forex: channel {channel_id} not found — task exiting.")
            self._cancel_channel(channel_id)
            return

        state = self.channel_states.get(channel_id)
        if not state:
            return

        # Immediate first post
        logger.info(f"Forex: immediate post → #{channel.name}")
        await self._post_forex_update(channel)

        tz_obj = pytz.timezone(FOREX_TIMEZONE)

        while state.get("running", False):
            try:
                # Compute seconds until the next scheduled time
                now_local = datetime.now(tz_obj)
                target = now_local.replace(
                    hour=FOREX_SCHEDULE_HOUR,
                    minute=FOREX_SCHEDULE_MINUTE,
                    second=0,
                    microsecond=0,
                )
                if target <= now_local:
                    # Already past today's window → schedule for tomorrow
                    from datetime import timedelta
                    target += timedelta(days=1)

                wait_seconds = (target - now_local).total_seconds()
                logger.info(
                    f"Forex: #{channel.name} next post in {wait_seconds / 3600:.2f}h "
                    f"at {FOREX_SCHEDULE_HOUR:02d}:{FOREX_SCHEDULE_MINUTE:02d} {FOREX_TIMEZONE}"
                )

                await asyncio.sleep(wait_seconds)

                if not state.get("running", False):
                    break

                logger.info(f"Forex: scheduled post → #{channel.name}")
                await self._post_forex_update(channel)

            except asyncio.CancelledError:
                logger.info(f"Forex: scheduler task for #{channel.name} cancelled.")
                break
            except Exception as exc:
                logger.error(f"Forex scheduler loop error: {exc}\n{traceback.format_exc()}")
                await asyncio.sleep(60)  # Brief pause before retry

        logger.info(f"Forex: scheduler loop for channel {channel_id} stopped.")

    # -----------------------------------------------------------------------
    # Public API — called by the dispatcher cog
    # -----------------------------------------------------------------------

    async def start_in_channel(self, ctx: commands.Context):
        """Start the forex notifier in the channel where *ctx* was sent."""
        channel_id = ctx.channel.id

        if channel_id in self.channel_states and self.channel_states[channel_id].get("running"):
            await ctx.send("⚠️ Forex notifier is already running in this channel.")
            return

        self.channel_states[channel_id] = {"running": True, "task": None}
        task = asyncio.create_task(self._scheduler_loop(channel_id))
        self.channel_states[channel_id]["task"] = task

        logger.info(f"Forex notifier started in #{ctx.channel.name} (id={channel_id})")
        await ctx.message.add_reaction("✅")
        await ctx.send(
            f"✅ **Forex Notifier** started in this channel.\n"
            f"📅 Daily posts at `{FOREX_SCHEDULE_HOUR:02d}:{FOREX_SCHEDULE_MINUTE:02d}` **{FOREX_TIMEZONE}**.\n"
            f"📤 Fetching and posting the first update now…"
        )

    async def stop_in_channel(self, ctx: commands.Context):
        """Stop the forex notifier in the channel where *ctx* was sent."""
        channel_id = ctx.channel.id

        if channel_id not in self.channel_states or not self.channel_states[channel_id].get("running"):
            await ctx.send("❌ Forex notifier is not running in this channel.")
            return

        self._cancel_channel(channel_id)
        await ctx.message.add_reaction("✅")
        await ctx.send("⏹️ **Forex Notifier** stopped in this channel.")
        logger.info(f"Forex notifier stopped in #{ctx.channel.name} (id={channel_id})")
