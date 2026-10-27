"""
Unified Discord Crypto Tool - Main Entrypoint
Runs Crypto Screening, VWAP Scanner, Forex Factory Notifier, and Degen token lookup as one process.
"""

import asyncio
import logging
import sys
import os

from config import DISCORD_TOKEN
from core.bot import CryptoBot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("crypto_tool.main")


def main():
    logger.info("==================================================")
    logger.info("   💎 UNIFIED DISCORD CRYPTO TOOL v2.1.0          ")
    logger.info("   Screening + VWAP + Forex + Degen               ")
    logger.info("==================================================")

    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        logger.error("❌ DISCORD_TOKEN or DISCORD_BOT_TOKEN is not configured in .env!")
        logger.error("Please copy .env.example to .env and insert your Discord Bot Token.")
        sys.exit(1)

    bot = CryptoBot()

    try:
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("🛑 Bot shutdown initiated by user.")
    except Exception as e:
        logger.critical(f"❌ Fatal bot crash: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
