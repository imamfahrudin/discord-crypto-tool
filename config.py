"""
Unified Configuration Module for Discord Crypto Tool
Loads environment variables and provides sensible defaults for all modules.
"""

import os
import json
import logging
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Logger setup
logger = logging.getLogger("crypto_tool.config")

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Data directory for SQLite database persistence
DATA_DIR = os.environ.get(
    "DATA_DIR",
    "/app/data" if os.path.exists("/app") else os.path.join(BASE_DIR, "data")
)
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "bot_states.db")

# Cache directory for exchange pairs and temporary data
CACHE_DIR = os.environ.get(
    "CACHE_DIR",
    "/app/cache" if os.path.exists("/app") else os.path.join(BASE_DIR, "cache")
)
os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Discord Bot Identity & Authentication
# ---------------------------------------------------------------------------
# Support both DISCORD_TOKEN and DISCORD_BOT_TOKEN for backward compatibility
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN") or ""
BOT_PREFIX = "!"
BOT_TITLE_PREFIX = os.environ.get("BOT_TITLE_PREFIX", "💎 CRYPTO SIGNAL —")
BOT_FOOTER_NAME = os.environ.get("BOT_FOOTER_NAME", "Crypto Bot")

# ---------------------------------------------------------------------------
# Network & Infrastructure
# ---------------------------------------------------------------------------
USE_WARP = os.environ.get("USE_WARP", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Screening Tool Module Settings
# ---------------------------------------------------------------------------
OHLC_LIMIT = int(os.environ.get("OHLC_LIMIT", 500))
SIGNAL_CONCURRENCY = int(os.environ.get("SIGNAL_CONCURRENCY", 2))

# ---------------------------------------------------------------------------
# VWAP Scanner Module Settings
# ---------------------------------------------------------------------------
MAX_SYMBOLS = int(os.environ.get("MAX_SYMBOLS", 120))
REFRESH_INTERVAL = os.environ.get("REFRESH_INTERVAL", "300,900,1800,3600")
MIN_VOLUME_M = float(os.environ.get("MIN_VOLUME_M", 0.3))
CANDLE_FETCH_CONCURRENCY = int(os.environ.get("CANDLE_FETCH_CONCURRENCY", 20))
ENABLE_WEBSOCKET_PRICES = os.environ.get("ENABLE_WEBSOCKET_PRICES", "false").lower() == "true"

TOP_N = int(os.environ.get("TOP_N", 15))
STRONG_SCORE = int(os.environ.get("STRONG_SCORE", 80))
BUY_SCORE = int(os.environ.get("BUY_SCORE", 25))
SELL_SCORE = int(os.environ.get("SELL_SCORE", -25))
STRONG_SELL_SCORE = int(os.environ.get("STRONG_SELL_SCORE", -80))

DEFAULT_SESSION_WEIGHTS = {
    "Sydney": 0.6,
    "Tokyo": 0.8,
    "London": 1.0,
    "New York": 1.2
}
_raw_weights = os.environ.get("SESSION_WEIGHTS")
if _raw_weights:
    try:
        SESSION_WEIGHTS = json.loads(_raw_weights)
    except Exception as e:
        logger.warning(f"Failed to parse SESSION_WEIGHTS JSON ({e}), using default")
        SESSION_WEIGHTS = DEFAULT_SESSION_WEIGHTS
else:
    SESSION_WEIGHTS = DEFAULT_SESSION_WEIGHTS

TABLE_FOOTER_TEXT = os.environ.get("TABLE_FOOTER_TEXT", "")
EMBED_FOOTER_TEXT = os.environ.get("EMBED_FOOTER_TEXT", "")

RATE_LIMIT_MIN_INTERVAL = float(os.environ.get("RATE_LIMIT_MIN_INTERVAL", "1.0"))
RATE_LIMIT_MAX_BURST = int(os.environ.get("RATE_LIMIT_MAX_BURST", "3"))
UPDATE_STAGGER_DELAY = float(os.environ.get("UPDATE_STAGGER_DELAY", "0.5"))
