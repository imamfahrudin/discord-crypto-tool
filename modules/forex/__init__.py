"""
Forex Factory Notifier Module
Provides scheduled daily Forex Factory economic calendar alerts posted directly to Discord channels.
"""

from .cog import ForexCog

async def setup(bot):
    await bot.add_cog(ForexCog(bot))
