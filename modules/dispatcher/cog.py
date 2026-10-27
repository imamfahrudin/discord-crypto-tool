"""
Dispatcher Cog for discord-crypto-tool.

Owns the unified !start <feature> and !stop <feature> prefix commands.
Routing table:
    vwap  → VwapCog.start_in_channel / VwapCog.stop_in_channel
    forex → ForexCog.start_in_channel / ForexCog.stop_in_channel

Usage examples:
    !start vwap    — start VWAP scanner in current channel
    !stop vwap     — stop  VWAP scanner in current channel
    !start forex   — start Forex Factory notifier in current channel
    !stop forex    — stop  Forex Factory notifier in current channel
    !start         — shows usage hint (no feature specified)
    !start unknown — shows usage hint (unknown feature)
"""

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("crypto_tool.dispatcher")

# Map feature name → (cog_name, start_method, stop_method)
FEATURE_MAP = {
    "vwap":  ("VwapCog",  "start_in_channel", "stop_in_channel"),
    "forex": ("ForexCog", "start_in_channel", "stop_in_channel"),
}

USAGE_HINT = (
    "⚠️ **Usage:** `!start <feature>` or `!stop <feature>`\n"
    "Available features: `vwap`, `forex`\n\n"
    "**Examples:**\n"
    "• `!start vwap`  — start live VWAP scanner\n"
    "• `!stop vwap`   — stop  live VWAP scanner\n"
    "• `!start forex` — start Forex Factory notifier\n"
    "• `!stop forex`  — stop  Forex Factory notifier"
)


class DispatcherCog(commands.Cog):
    """Routes !start / !stop to the appropriate feature cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _dispatch(self, ctx: commands.Context, action: str, feature: str | None):
        """
        Look up *feature* in the routing table and call action on the cog.

        Parameters
        ----------
        action  : "start" or "stop"
        feature : the first argument supplied by the user, e.g. "vwap"
        """
        if not feature:
            await ctx.send(USAGE_HINT)
            return

        feature = feature.strip().lower()
        if feature not in FEATURE_MAP:
            await ctx.send(
                f"❓ Unknown feature: `{feature}`.\n{USAGE_HINT}"
            )
            return

        cog_name, start_method, stop_method = FEATURE_MAP[feature]
        cog = self.bot.get_cog(cog_name)
        if cog is None:
            await ctx.send(
                f"⚠️ The `{feature}` module is not loaded. Please contact the bot admin."
            )
            return

        method_name = start_method if action == "start" else stop_method
        method = getattr(cog, method_name, None)
        if method is None:
            await ctx.send(f"⚠️ Internal error: method `{method_name}` not found on `{cog_name}`.")
            return

        await method(ctx)

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    @commands.command(name="start")
    async def start_command(self, ctx: commands.Context, feature: str = None):
        """
        Start a bot feature in this channel.

        Usage: !start <feature>
        Features: vwap, forex
        """
        await self._dispatch(ctx, "start", feature)

    @commands.command(name="stop")
    async def stop_command(self, ctx: commands.Context, feature: str = None):
        """
        Stop a bot feature in this channel.

        Usage: !stop <feature>
        Features: vwap, forex
        """
        await self._dispatch(ctx, "stop", feature)
