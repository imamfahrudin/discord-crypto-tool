"""
VWAP Scanner Bot Module
Provides multi-session VWAP analysis, real-time indicator scoring, and live-updating Discord tables.
"""

from .cog import VwapCog

async def setup(bot):
    await bot.add_cog(VwapCog(bot))
