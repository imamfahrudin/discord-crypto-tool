"""
Trading Session Notifier cog.

Commands (routed by the dispatcher):
    !start session — bind this channel, persist it, post the startup embed
    !stop session  — cancel the schedule and forget the channel

One notifier channel is stored in session_notifier_state (bot_states.db).
That row is separate from VWAP channel_states and forex_channel_states.
If the row says the notifier was running, startup resumes the schedule and
does not post the startup embed again.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime

import discord
from discord.ext import commands
from pytz import utc

from core.database import (
    load_session_notifier_state,
    remove_session_notifier_state,
    save_session_notifier_state,
)
from .schedule import (
    compute_sessions,
    next_event_batch,
    session_changes,
    session_start_embed,
    startup_embed,
    sync_embed,
)

logger = logging.getLogger("crypto_tool.session.cog")


class SessionCog(commands.Cog):
    """Posts trading-session open and daylight-saving updates to one channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_id: int | None = None
        self.guild_id: int | None = None
        self.running = False
        self.task: asyncio.Task | None = None
        self.sessions: dict = compute_sessions()

    async def on_bot_ready(self):
        """Called by core/bot.py once the gateway connection is open."""
        await self.restore_state()

    def cog_unload(self):
        """Cancel the schedule. The saved row stays so a restart can resume."""
        self._cancel_task()

    async def restore_state(self):
        """Resume the notifier when the saved row is still running."""
        saved = load_session_notifier_state()
        if not saved:
            logger.info("No saved session notifier to restore")
            return

        channel_id = saved["channel_id"]
        try:
            channel = await self._resolve_channel(channel_id, saved.get("guild_id"))
        except discord.HTTPException as exc:
            logger.warning("Session notifier: could not fetch channel %s, keeping saved state: %s", channel_id, exc)
            return
        if channel is None:
            logger.warning("Session notifier channel %s is not accessible; dropping saved state", channel_id)
            remove_session_notifier_state()
            return

        self.channel_id = channel_id
        self.guild_id = saved.get("guild_id")
        self.sessions = compute_sessions()
        self.running = True
        self.task = asyncio.create_task(self._scheduler_loop())
        logger.info(
            "Restored session notifier in #%s (startup embed is not repeated)",
            getattr(channel, "name", channel_id),
        )

    def _cancel_task(self):
        self.running = False
        task = self.task
        self.task = None
        if task and not task.done():
            task.cancel()

    async def _resolve_channel(self, channel_id: int, guild_id: int | None):
        channel = self.bot.get_channel(channel_id)
        if channel is None and guild_id:
            guild = self.bot.get_guild(guild_id)
            if guild:
                channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden):
                channel = None
        return channel

    async def _send_embed(self, payload: dict) -> bool:
        """Post an embed to the saved channel. Drop the row if the channel is gone."""
        if self.channel_id is None:
            return False
        try:
            channel = await self._resolve_channel(self.channel_id, self.guild_id)
        except discord.HTTPException as exc:
            logger.warning("Session notifier: could not fetch channel %s: %s", self.channel_id, exc)
            return False
        if channel is None:
            logger.error("Session notifier channel %s disappeared; stopping", self.channel_id)
            self._cancel_task()
            self.channel_id = None
            remove_session_notifier_state()
            return False
        try:
            await channel.send(embed=discord.Embed.from_dict(payload))
            return True
        except discord.NotFound:
            logger.error("Session notifier channel %s was deleted; stopping", self.channel_id)
            self._cancel_task()
            self.channel_id = None
            remove_session_notifier_state()
            return False
        except Exception as exc:
            logger.error("Session notifier failed to post: %s\n%s", exc, traceback.format_exc())
            return False

    async def _scheduler_loop(self):
        """
        Sleep until the next session open or the 06:00 UTC daylight-saving sync.

        After a sync, later waits use the updated UTC hours.
        """
        while self.running:
            try:
                now = datetime.now(utc)
                when, batch = next_event_batch(self.sessions, now)
                wait_seconds = (when - now).total_seconds()
                logger.info(
                    "Session notifier: next event in %.2fh at %s UTC (%s)",
                    wait_seconds / 3600,
                    when.strftime("%Y-%m-%d %H:%M"),
                    ", ".join(item[2] or "sync" for item in batch),
                )
                await asyncio.sleep(max(wait_seconds, 0))
                if not self.running:
                    break

                fired_at = datetime.now(utc)
                for kind, _event_time, name in batch:
                    if not self.running:
                        break
                    if kind == "sync":
                        updated = compute_sessions(fired_at)
                        changes = session_changes(self.sessions, updated)
                        self.sessions = updated
                        if changes:
                            logger.info("Session windows changed: %s", changes)
                            await self._send_embed(sync_embed(changes, fired_at))
                        else:
                            logger.info("Session sync: no window changes")
                    else:
                        if name not in self.sessions:
                            continue
                        logger.info("Session notifier: %s started", name)
                        await self._send_embed(session_start_embed(name, self.sessions, fired_at))
            except asyncio.CancelledError:
                logger.info("Session notifier schedule cancelled")
                break
            except Exception as exc:
                logger.error("Session notifier loop error: %s\n%s", exc, traceback.format_exc())
                await asyncio.sleep(60)

        logger.info("Session notifier schedule stopped")

    async def start_in_channel(self, ctx: commands.Context):
        """Bind the notifier to this channel and post the startup embed."""
        if self.running:
            if self.channel_id == ctx.channel.id:
                await ctx.send("⚠️ Session notifier is already running in this channel.")
            else:
                await ctx.send(
                    "⚠️ Session notifier is already running in another channel. "
                    "Use `!stop session` first."
                )
            return

        guild = ctx.guild
        self.channel_id = ctx.channel.id
        self.guild_id = guild.id if guild else None
        self.sessions = compute_sessions()
        self.running = True
        save_session_notifier_state(
            ctx.channel.id,
            True,
            guild.name if guild else "DM",
            getattr(ctx.channel, "name", "DM"),
            self.guild_id,
        )
        self.task = asyncio.create_task(self._scheduler_loop())

        logger.info("Session notifier started in #%s (id=%s)", getattr(ctx.channel, "name", ctx.channel.id), ctx.channel.id)
        try:
            await ctx.message.add_reaction("✅")
        except Exception:
            pass
        await ctx.send(embed=discord.Embed.from_dict(startup_embed(self.sessions)))

    async def stop_in_channel(self, ctx: commands.Context):
        """Cancel scheduled posts and remove the saved channel."""
        if not self.running:
            await ctx.send("❌ Session notifier is not running.")
            return

        self._cancel_task()
        self.channel_id = None
        self.guild_id = None
        remove_session_notifier_state()
        try:
            await ctx.message.add_reaction("✅")
        except Exception:
            pass
        await ctx.send("⏹️ **Session notifier** stopped. Scheduled tasks cancelled.")
        logger.info("Session notifier stopped from #%s", getattr(ctx.channel, "name", ctx.channel.id))
