"""
Trading Session Notifier module.
Posts session-open alerts directly to one Discord channel.
"""

from .cog import SessionCog


async def setup(bot):
    await bot.add_cog(SessionCog(bot))
