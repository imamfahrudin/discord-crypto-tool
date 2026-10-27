# Discord Crypto Tool 🤖💎

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.3+-5865F2.svg)](https://discordpy.readthedocs.io/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An intelligent, unified Discord bot combining real-time cryptocurrency technical analysis screening (RSI, EMA, SMC/FVG) and continuous live-updating multi-session VWAP ranking tables into a single high-performance, low-RAM process.

---

## 🌟 Highlights & Why Combine?

Running two separate Python Discord bots consumes redundant system memory (two Python runtimes, two Discord gateway WebSocket connections, duplicate copies of heavy numeric libraries like Matplotlib and Pandas, and separate background daemons). 

**Discord Crypto Tool** consolidates:
- **`discord-crypto-screening-tool`** (Signals, scalp scanner, chart generation, multi-exchange support)
- **`discord-crypto-vwap-tool`** (Automated multi-session VWAP scanner tables with live Discord message editing)

### Key Benefits
- **50%+ Lower Memory Footprint**: Single Python process, single gateway connection, capped glibc malloc arenas (`MALLOC_ARENA_MAX=2`), shared image generator memory trimming (`malloc_trim`).
- **Zero Command Collisions**: All commands from both bots work seamlessly without conflict.
- **Single Token**: Requires only one Discord Bot Application & Token.
- **Modular Cog Architecture**: Pluggable modules in `modules/` registered via a central loader. Adding future modules is effortless.
- **Persistent State**: SQLite database stores active scanner tables and session ranking history across restarts.

---

## 📁 Merged Project Structure

```text
discord-crypto-tool/
├── .env.example              # Unified environment configuration template
├── .gitignore                # Git ignore rules for virtualenvs, DBs, and caches
├── Dockerfile                # Production Dockerfile with Cloudflare WARP and memory limits
├── docker-compose.yml        # Docker Compose configuration (single container, 384MB limit)
├── LICENSE                   # MIT License
├── README.md                 # Complete documentation
├── requirements.txt          # Consolidated dependencies
├── config.py                 # Central configuration with env fallbacks
├── main.py                   # Main process entrypoint
│
├── core/                     # Shared bot infrastructure
│   ├── __init__.py
│   ├── bot.py                # Unified CryptoBot class (cog loader, message dispatcher)
│   ├── database.py           # Thread-safe SQLite database manager
│   ├── rate_limiter.py       # Discord message edit rate limiter (prevents HTTP 429)
│   └── utils.py              # Formatting, RR calculation, and memory release helpers
│
├── modules/                  # Pluggable feature modules
│   │
│   ├── screening/            # Module: Crypto Screening & Position Setups
│   │   ├── __init__.py       # Cog loader setup
│   │   ├── cog.py            # Commands: !signal, !scan, !scalp, !coinlist, !ping, $quick, /help
│   │   ├── signal_logic.py   # Trade plan engine (EMA, RSI, MACD, Stochastic, FVG/SMC)
│   │   ├── chart_generator.py# Candlestick chart generation with mplfinance & position boxes
│   │   ├── exchange_factory.py # Exchange abstraction router
│   │   ├── bybit_data.py     # Bybit linear futures data adapter
│   │   ├── binance_data.py   # Binance USD-M futures data adapter
│   │   ├── bitget_data.py    # Bitget USDT futures data adapter
│   │   ├── gate_data.py      # Gate.io USDT futures data adapter
│   │   └── views.py          # Interactive pagination views for !coinlist
│   │
│   └── vwap/                 # Module: Multi-Session VWAP Scanner
│       ├── __init__.py       # Cog loader setup
│       ├── cog.py            # Commands: !start, !stop, !session, !health & background loops
│       ├── table_generator.py# Graphic table image generator with ranking deltas (▲/▼)
│       ├── rank_db.py        # Ranking history and position change tracking
│       ├── sessions/         # Session detection (Sydney, Tokyo, London, New York) & VWAP
│       │   ├── session_manager.py
│       │   └── vwap.py
│       ├── indicators/       # Lightweight pure-python indicators (RSI, MACD, ATR, Stochastic)
│       ├── bybit/            # Bybit async REST candle fetcher & optional WebSocket price stream
│       │   ├── rest.py
│       │   └── websocket.py
│       ├── engine/           # Scoring and classification engine
│       │   ├── scanner_engine.py
│       │   ├── scoring.py
│       │   ├── mtf_engine.py
│       │   └── signal_engine.py
│       └── output/           # Output formatting & fallback text table
│           ├── colors.py
│           └── table.py
│
├── tests/                    # Offline verification test suite
│   ├── test_screening.py     # Tests chart & signal generation without Discord
│   └── test_vwap.py          # Tests table image generation without Discord
│
├── data/                     # SQLite database storage (persisted across restarts)
└── cache/                    # Exchange pairs disk cache
```

---

## 🚀 Quick Start

### Option 1: Docker (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/imamfahrudin/discord-crypto-tool.git
   cd discord-crypto-tool
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env and paste your Discord bot token
   nano .env
   ```

3. **Start with Docker Compose:**
   ```bash
   docker-compose up -d --build
   ```

4. **Check logs:**
   ```bash
   docker-compose logs -f
   ```

### Option 2: Local Python Environment

1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure `.env`:**
   ```bash
   cp .env.example .env
   ```

4. **Run the bot:**
   ```bash
   python main.py
   ```

---

## ⚙️ Configuration Reference (`.env`)

| Variable | Default | Description |
|---|---|---|
| `DISCORD_TOKEN` | *Required* | Your Discord Bot Token (supports `DISCORD_BOT_TOKEN` as fallback) |
| `BOT_TITLE_PREFIX` | `💎 CRYPTO SIGNAL —` | Embed title prefix for signal alerts |
| `BOT_FOOTER_NAME` | `Crypto Bot` | Footer branding text |
| `USE_WARP` | `false` | Enable Cloudflare WARP in Docker for DNS-over-HTTPS & exchange access |
| `OHLC_LIMIT` | `500` | Number of historical candles fetched for indicators |
| `SIGNAL_CONCURRENCY` | `2` | Max simultaneous signal/chart operations to bound RAM |
| `MAX_SYMBOLS` | `120` | Maximum Bybit linear futures symbols scanned by VWAP |
| `REFRESH_INTERVAL` | `300` | Refresh intervals in seconds (e.g. `300` or `300,900,1800`) |
| `MIN_VOLUME_M` | `0.3` | Minimum 24h trading volume (Million USDT) for VWAP inclusion |
| `CANDLE_FETCH_CONCURRENCY`| `20` | Max concurrent HTTP connections during VWAP scans |
| `ENABLE_WEBSOCKET_PRICES` | `false` | Real-time Bybit WebSocket ticker stream (keep false to minimize RAM/CPU) |
| `TOP_N` | `15` | Top N symbols displayed in the VWAP ranking table |
| `SESSION_WEIGHTS` | `{"Sydney": 0.6, "Tokyo": 0.8, "London": 1.0, "New York": 1.2}` | Multiplier weights per trading session |

---

## 🎮 Command Guide

### 1. Screening Tool Commands

| Command | Example | Description |
|---|---|---|
| `$COIN [tf] [dir] [exchange]` | `$BTC` or `$ETH 4h long binance` | Quick trading signal analysis with chart setup |
| `!signal <COIN> [tf] [dir]` | `!signal SOL 1h long ema20 ema50` | Full signal analysis with custom EMA periods |
| `!scan <COIN1 COIN2 ...>` | `!scan BTC ETH SOL binance` | Scans up to 5 coins across 1h/4h setups, selects highest confidence |
| `!scalp <COIN1 COIN2 ...>` | `!scalp BTC ETH SOL` | Scalp scanner focusing on 15m & 30m setups |
| `!coinlist [exchange]` | `!coinlist binance` | Paginated list of available futures pairs |
| `!ping` | `!ping` | Displays bot latency and exchange API benchmark |
| `/help` | `/help` | Interactive slash command guide (Indonesian & English) |

> **Interactive Buttons:** Every signal embed includes a direct link to **TradingView** and a dynamic button to toggle between EMA sets (e.g. `EMA 13/21` ↔ `EMA 25/50`).

### 2. VWAP Scanner Commands

| Command | Example | Description |
|---|---|---|
| `!start` | `!start` | Starts continuous live-updating VWAP ranking table in the channel |
| `!stop` | `!stop` | Stops the scanner in the current channel and removes from database |
| `!session` | `!session` | Displays active session, weights, upcoming sessions, and triggers manual refresh |
| `!health` | `!health` | Inspects real-time health and update latency of all active channel tables |

---

## 🔄 Notes for Migrating Users

If you previously ran `discord-crypto-screening-tool` and `discord-crypto-vwap-tool`:

1. **Bot Token**: You only need **one** Discord bot token now! You can use the token from either bot.
2. **Discord Application Intents**: Make sure **Message Content Intent** is toggled ON in the [Discord Developer Portal](https://discord.com/developers/applications).
3. **Old Channels**: When running `!start`, the bot will begin updating in your current channel and record the state in `data/bot_states.db`.
4. **Zero Conflicts**: All prefixes (`$`, `!`) and commands work exactly as they did before.

---

## 🧩 Adding a New Bot Module in the Future

Adding new modules (e.g., Arbitrage, News Summarizer, On-chain alerts) is modular and straightforward:

1. **Create module directory**:
   ```
   modules/
   └── my_feature/
       ├── __init__.py
       └── cog.py
   ```

2. **Define your Cog in `modules/my_feature/cog.py`**:
   ```python
   from discord.ext import commands

   class MyFeatureCog(commands.Cog):
       def __init__(self, bot):
           self.bot = bot

       @commands.command(name="mycommand")
       async def my_command(self, ctx):
           await ctx.reply("Hello from MyFeature module!")
   ```

3. **Define extension loader in `modules/my_feature/__init__.py`**:
   ```python
   from .cog import MyFeatureCog

   async def setup(bot):
       await bot.add_cog(MyFeatureCog(bot))
   ```

4. **Register in `core/bot.py`**:
   Add `"modules.my_feature"` to the `modules` list inside `setup_hook()`:
   ```python
   modules = [
       "modules.screening",
       "modules.vwap",
       "modules.my_feature",  # <--- your new module
   ]
   ```
   The bot will automatically discover, load, and sync slash commands on startup!

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
