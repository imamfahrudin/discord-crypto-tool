"""
Bitcoinist AI RSS summarizer.
Posts article summaries directly to one Discord channel.
"""

from .cog import NewsCog


async def setup(bot):
    await bot.add_cog(NewsCog(bot))
