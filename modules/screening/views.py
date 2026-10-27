"""
UI Views and Components for the Screening Module.
"""

import discord
from config import BOT_FOOTER_NAME


class CoinListView(discord.ui.View):
    """Paginated View for browsing available trading coins."""

    def __init__(self, chunks, total_coins, exchange="BYBIT", timeout=300):
        super().__init__(timeout=timeout)
        self.chunks = chunks
        self.total_coins = total_coins
        self.exchange = exchange.upper()
        self.current_page = 0
        self.total_pages = len(chunks)
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.current_page == 0)
        self.children[1].disabled = (self.current_page >= self.total_pages - 1)

    def get_embed(self):
        chunk = self.chunks[self.current_page]
        start_num = self.current_page * len(self.chunks[0]) + 1
        coin_list = "\n".join(f"{start_num + i}. {coin}" for i, coin in enumerate(chunk))

        embed = discord.Embed(
            title=f"🪙 Available Coins ({self.exchange}) — Page {self.current_page + 1}/{self.total_pages}",
            description=f"Supported trading pairs on {self.exchange} Futures:\n\n{coin_list}",
            color=0x00FF88
        )
        embed.set_footer(text=f"{BOT_FOOTER_NAME} • Total coins: {self.total_coins} • Page {self.current_page + 1}/{self.total_pages}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary, emoji="⬅️")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, emoji="➡️")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
