"""
Bitcoinist news cog.

Commands (routed by the dispatcher):
    !start news — bind this channel, persist it, and check the feed immediately
    !stop news  — cancel the poll task

One channel and the last processed article time live in news_state
(bot_states.db). That row is separate from VWAP, Forex, degen, and session
state. If the row says the feature was running, startup resumes the same
poll loop and does not post a start message. Articles at or before
last_processed are not sent again.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone

import discord
from discord.ext import commands

from config import NEWS_CONTENT, NEWS_POLL_INTERVAL
from core.database import load_news_state, save_news_state
from .feed import articles_since, build_embed_dict, summarize_article

logger = logging.getLogger("crypto_tool.news.cog")

ARTICLE_PAUSE_SECONDS = 2
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


class NewsCog(commands.Cog):
    """Polls Bitcoinist and posts AI summaries to one channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_id: int | None = None
        self.guild_id: int | None = None
        self.server_name: str | None = None
        self.channel_name: str | None = None
        self.running = False
        self.task: asyncio.Task | None = None
        self.last_processed = _EPOCH

    async def on_bot_ready(self):
        """Called by core/bot.py once the gateway connection is open."""
        await self.restore_state()

    def cog_unload(self):
        """Cancel the poll. The saved row stays so a restart can resume."""
        self._cancel_task()

    async def restore_state(self):
        """Load the channel and last article time. Resume only when it was running."""
        saved = load_news_state()
        if not saved:
            logger.info("No saved news state to restore")
            return

        self.last_processed = _parse_last_processed(saved.get("last_processed"))
        self.channel_id = saved.get("channel_id")
        self.guild_id = saved.get("guild_id")
        self.server_name = saved.get("server_name")
        self.channel_name = saved.get("channel_name")

        if not saved.get("running"):
            logger.info(
                "News is stopped. Last processed article time kept at %s",
                self.last_processed.isoformat(),
            )
            return

        if self.channel_id is None:
            logger.warning("News was marked running without a channel; leaving it stopped")
            self._persist(running=False)
            return

        try:
            channel = await self._resolve_channel(self.channel_id, self.guild_id)
        except discord.HTTPException as exc:
            logger.warning("News: could not fetch channel %s, keeping saved state: %s", self.channel_id, exc)
            return
        if channel is None:
            logger.warning("News channel %s is not accessible; leaving the saved article time", self.channel_id)
            self.running = False
            self._persist(running=False)
            return

        self.running = True
        self.task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Restored news in #%s from %s (no start message)",
            getattr(channel, "name", self.channel_id),
            self.last_processed.isoformat(),
        )

    def _cancel_task(self):
        self.running = False
        task = self.task
        self.task = None
        if task and not task.done():
            task.cancel()

    def _persist(self, running: bool | None = None):
        if self.channel_id is None and self.last_processed == _EPOCH:
            return
        last_value = None if self.last_processed == _EPOCH else self.last_processed.isoformat()
        save_news_state(
            self.channel_id,
            self.running if running is None else running,
            last_value,
            self.server_name,
            self.channel_name,
            self.guild_id,
        )

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

    async def _poll_loop(self):
        """One loop: check immediately, then every NEWS_POLL_INTERVAL seconds."""
        while self.running:
            try:
                await self._run_cycle()
                if not self.running:
                    break
                logger.info("News check done. Next check in %ss", NEWS_POLL_INTERVAL)
                await asyncio.sleep(NEWS_POLL_INTERVAL)
            except asyncio.CancelledError:
                logger.info("News poll cancelled")
                break
            except Exception as exc:
                logger.error("News poll error: %s\n%s", exc, traceback.format_exc())
                await asyncio.sleep(60)
        logger.info("News poll stopped")

    async def _run_cycle(self):
        if self.channel_id is None or not self.running:
            return

        loop = asyncio.get_running_loop()
        articles = await loop.run_in_executor(None, articles_since, self.last_processed)
        if articles is None:
            logger.error("News feed could not be fetched; last processed time unchanged")
            return
        if not articles:
            logger.info("No new Bitcoinist articles since %s", self.last_processed.isoformat())
            return

        logger.info("Found %s new article(s)", len(articles))
        for index, article in enumerate(articles):
            if not self.running:
                break
            summary = await loop.run_in_executor(None, summarize_article, article["content"])
            if summary:
                posted = await self._post_article(article, summary)
                if not posted and not self.running:
                    break
            else:
                logger.error("No summary for '%s'; advancing past it", article["title"])

            # The original loop advances the checkpoint even when the API fails,
            # so a broken article is not retried forever.
            if article["published"] > self.last_processed:
                self.last_processed = article["published"]
                self._persist()

            if index < len(articles) - 1 and self.running:
                await asyncio.sleep(ARTICLE_PAUSE_SECONDS)

    async def _post_article(self, article: dict, summary: str) -> bool:
        try:
            channel = await self._resolve_channel(self.channel_id, self.guild_id)
        except discord.HTTPException as exc:
            logger.warning("News: could not fetch channel %s: %s", self.channel_id, exc)
            return False
        if channel is None:
            logger.error("News channel %s disappeared; stopping", self.channel_id)
            self._cancel_task()
            self._persist(running=False)
            return False

        embed = discord.Embed.from_dict(build_embed_dict(article, summary))
        content = NEWS_CONTENT.strip() or None
        try:
            await channel.send(content=content, embed=embed)
            logger.info("Posted news: %s", article["title"])
            return True
        except discord.NotFound:
            logger.error("News channel %s was deleted; stopping", self.channel_id)
            self._cancel_task()
            self._persist(running=False)
            return False
        except Exception as exc:
            logger.error("News failed to post: %s\n%s", exc, traceback.format_exc())
            return False

    async def start_in_channel(self, ctx: commands.Context):
        """Bind this channel and run the first feed check immediately."""
        if self.running:
            if self.channel_id == ctx.channel.id:
                await ctx.send("⚠️ News is already running in this channel.")
            else:
                await ctx.send(
                    "⚠️ News is already running in another channel. Use `!stop news` first."
                )
            return

        guild = ctx.guild
        self.channel_id = ctx.channel.id
        self.guild_id = guild.id if guild else None
        self.server_name = guild.name if guild else "DM"
        self.channel_name = getattr(ctx.channel, "name", "DM")
        self.running = True
        self._persist(running=True)
        self.task = asyncio.create_task(self._poll_loop())

        logger.info("News started in #%s (id=%s)", self.channel_name, self.channel_id)
        try:
            await ctx.message.add_reaction("✅")
        except Exception:
            pass
        await ctx.send(
            "✅ **Bitcoinist News** started in this channel. Checking the feed now."
        )

    async def stop_in_channel(self, ctx: commands.Context):
        """Cancel the poll and keep the last processed article time."""
        if not self.running:
            await ctx.send("❌ News is not running.")
            return

        self._cancel_task()
        self._persist(running=False)
        try:
            await ctx.message.add_reaction("✅")
        except Exception:
            pass
        await ctx.send("⏹️ **Bitcoinist News** stopped. The feed check was cancelled.")
        logger.info("News stopped from #%s", getattr(ctx.channel, "name", ctx.channel.id))


def _parse_last_processed(value: str | None) -> datetime:
    if not value:
        return _EPOCH
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Ignoring invalid news last_processed value: %s", value)
        return _EPOCH
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
