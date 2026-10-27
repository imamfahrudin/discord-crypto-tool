"""
Degen Token Lookup Module
Replies to pasted contract addresses with DexScreener market data,
a GeckoTerminal candlestick chart, and price-comparison buttons.
"""

from .cog import DegenCog


async def setup(bot):
    await bot.add_cog(DegenCog(bot))
