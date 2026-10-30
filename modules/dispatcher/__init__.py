"""
Command Dispatcher Module
Provides the unified !start <feature> / !stop <feature> prefix commands and
routes them to the correct feature cog.

Supported features:
    vwap     — VWAP live-updating scanner
    forex    — Forex Factory daily calendar notifier
    session  — trading-session open alerts
"""

from .cog import DispatcherCog

async def setup(bot):
    await bot.add_cog(DispatcherCog(bot))
