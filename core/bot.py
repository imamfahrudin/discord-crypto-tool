"""
Core Discord Bot class for discord-crypto-tool.
Manages centralized command processing, module loading, and event routing.
"""

import discord
from discord.ext import commands
import logging
import traceback
from config import BOT_PREFIX, BOT_TITLE_PREFIX, BOT_FOOTER_NAME
from core.database import init_database

logger = logging.getLogger("crypto_tool.bot")


class CryptoBot(commands.Bot):
    """
    Unified Discord Bot consolidating Screening and VWAP functionalities.
    """

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=BOT_PREFIX,
            intents=intents,
            help_command=None  # Custom help command provided via cog / slash command
        )
        self.bot_title_prefix = BOT_TITLE_PREFIX
        self.bot_footer_name = BOT_FOOTER_NAME

    async def setup_hook(self):
        """Lifecycle hook invoked before the bot connects to Discord."""
        logger.info("Initializing database...")
        init_database()

        # List of modular extensions to load.
        # NOTE: 'modules.dispatcher' MUST be last so it can find the other
        # cogs via bot.get_cog() in its routing table.
        modules = [
            "modules.screening",
            "modules.vwap",
            "modules.forex",
            "modules.degen",
            "modules.dispatcher",   # owns !start / !stop — load last
        ]

        logger.info("Loading bot modules...")
        for module in modules:
            try:
                await self.load_extension(module)
                logger.info(f"✅ Module loaded: {module}")
            except Exception as e:
                logger.error(f"❌ Failed to load module {module}: {e}")
                traceback.print_exc()

    async def on_ready(self):
        """Invoked when bot establishes connection with Discord gateway."""
        logger.info(f"🤖 Connected as {self.user} (ID: {self.user.id})")
        logger.info(f"📊 Present in {len(self.guilds)} servers")

        # Sync slash commands with Discord
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} slash command(s)")
        except Exception as e:
            logger.error(f"❌ Error syncing slash commands: {e}")

        # Notify cogs that bot is ready for post-connection setup (restoring states, caches)
        for cog_name, cog in self.cogs.items():
            if hasattr(cog, "on_bot_ready"):
                try:
                    await cog.on_bot_ready()
                except Exception as e:
                    logger.error(f"❌ Error in {cog_name}.on_bot_ready: {e}")

        logger.info("🚀 All systems operational! Screening, VWAP, Forex, and Degen modules ready.")

    async def on_message(self, message: discord.Message):
        """
        Unified message handler routing prefix commands and quick triggers.
        """
        # Ignore messages from bots (including self)
        if message.author.bot or message.author == self.user:
            return

        # 1. Quick signal command ($BTC, $ETH 4h long, etc.)
        if message.content.startswith("$"):
            screening_cog = self.get_cog("ScreeningCog")
            if screening_cog and hasattr(screening_cog, "handle_quick_signal"):
                await message.add_reaction("🫡")
                await screening_cog.handle_quick_signal(message)
            return

        # 2. Standard prefix command (!signal, !start, !stop, !health, etc.)
        if message.content.startswith(self.command_prefix):
            try:
                await message.add_reaction("🫡")
            except Exception:
                pass
            await self.process_commands(message)
            return

        # 3. Degen token lookup. A pasted contract address is not a prefix command.
        #    $ quick-signals and ! commands are handled above and are not scanned.
        degen_cog = self.get_cog("DegenCog")
        if degen_cog and hasattr(degen_cog, "handle_token_query"):
            await degen_cog.handle_token_query(message)

    async def on_command_error(self, ctx, error):
        """Handle unhandled command errors gracefully."""
        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown ! commands
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"⚠️ Missing argument: `{error.param.name}`. Gunakan `/help` untuk panduan.")
            return

        logger.error(f"Command error in {ctx.command}: {error}")
        traceback.print_exc()
        try:
            await ctx.send(f"❌ Terjadi kesalahan: `{str(error)[:120]}`")
        except Exception:
            pass
