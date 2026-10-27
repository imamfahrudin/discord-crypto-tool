"""
Screening Bot Module
Provides real-time technical analysis, multi-exchange signals, scalp scans, and chart generation.
"""

from .cog import ScreeningCog

async def setup(bot):
    await bot.add_cog(ScreeningCog(bot))
