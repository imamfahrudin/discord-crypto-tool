"""
DexScreener, CoinGecko, and GeckoTerminal clients for the degen module.

One aiohttp session, owned by DegenCog, is shared by every degen request.
Screening, VWAP, and Forex do not call these hosts, so there is no shared cache.
"""

import logging
from datetime import datetime, timezone
from urllib.parse import quote

logger = logging.getLogger("crypto_tool.degen.api")

COINGECKO_PLATFORM = {
    "ethereum": "ethereum",
    "bsc": "binance-smart-chain",
    "polygon": "polygon-pos",
    "arbitrum": "arbitrum-one",
    "optimism": "optimistic-ethereum",
    "base": "base",
    "avalanche": "avalanche",
    "solana": "solana",
}

GECKO_NETWORK = {
    "ethereum": "eth",
    "bsc": "bsc",
    "polygon": "polygon_pos",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "base": "base",
    "avalanche": "avax",
    "solana": "solana",
}


def gecko_network_for(chain_id):
    """Map a DexScreener chain id onto a GeckoTerminal network slug."""
    if not chain_id:
        return ""
    return GECKO_NETWORK.get(chain_id, chain_id)


async def _read_json(response):
    return await response.json(content_type=None)


async def fetch_token_data(session, query):
    """First DexScreener pair for a contract address, or None."""
    url = f"https://api.dexscreener.com/latest/dex/search?q={quote(str(query))}"
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"API request failed: {response.status} {response.reason}")
            data = await _read_json(response)
    except Exception as exc:
        logger.info("DexScreener API error for query %s: %s", query, exc)
        logger.info("API URL attempted: %s", url)
        raise

    pairs = (data or {}).get("pairs") or []
    if not pairs:
        return None
    return pairs[0]


def _coingecko_date(timestamp):
    """CoinGecko /history requires dd-mm-yyyy. The Node bot sent YYYY-MM-DD, which 400s."""
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%d-%m-%Y")


async def fetch_historical_price(session, contract_address, chain_id, timestamp):
    """Daily USD price and market cap from CoinGecko, or None."""
    platform = None
    date_string = None
    url = None
    try:
        platform = COINGECKO_PLATFORM.get((chain_id or "").lower())
        if not platform:
            logger.info("Unsupported chain: %s", chain_id)
            return None

        date_string = _coingecko_date(timestamp)
        url = (
            f"https://api.coingecko.com/api/v3/coins/{platform}/contract/"
            f"{contract_address}/history?date={date_string}&localization=false"
        )
        async with session.get(url) as response:
            if response.status == 404:
                logger.info("Token not found on CoinGecko for %s on %s", contract_address, platform)
                return None
            if response.status != 200:
                raise RuntimeError(f"CoinGecko API request failed: {response.status} {response.reason}")
            data = await _read_json(response)

        market = (data or {}).get("market_data")
        if not market:
            logger.info("No market data available for %s on %s", contract_address, date_string)
            return None

        return {
            "price": (market.get("current_price") or {}).get("usd"),
            "marketCap": (market.get("market_cap") or {}).get("usd"),
            "volume24h": (market.get("total_volume") or {}).get("usd"),
            "timestamp": timestamp,
        }
    except Exception as exc:
        logger.info("CoinGecko historical API error for %s: %s", contract_address, exc)
        logger.info("Network: %s, Platform: %s, Date: %s", chain_id, platform, date_string)
        logger.info("API URL attempted: %s", url)
        return None


async def fetch_current_price_from_coingecko(session, contract_address, chain_id):
    """Spot USD price from CoinGecko simple/token_price, or None."""
    platform = None
    url = None
    try:
        platform = COINGECKO_PLATFORM.get((chain_id or "").lower())
        if not platform:
            logger.info("Unsupported chain: %s", chain_id)
            return None

        url = (
            f"https://api.coingecko.com/api/v3/simple/token_price/{platform}"
            f"?contract_addresses={contract_address}&vs_currencies=usd"
            f"&include_market_cap=true&include_24hr_vol=true&include_24hr_change=true"
        )
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"CoinGecko API request failed: {response.status} {response.reason}")
            data = await _read_json(response)

        token_data = (data or {}).get(contract_address.lower())
        if not token_data:
            logger.info("Token not found on CoinGecko: %s", contract_address)
            return None

        return {
            "price": token_data.get("usd"),
            "marketCap": token_data.get("usd_market_cap"),
            "volume24h": token_data.get("usd_24h_vol"),
            "priceChange24h": token_data.get("usd_24h_change"),
            "timestamp": int(datetime.now(tz=timezone.utc).timestamp()),
        }
    except Exception as exc:
        logger.info("CoinGecko API error for %s: %s", contract_address, exc)
        logger.info("Network: %s, Platform: %s", chain_id, platform)
        logger.info("API URL attempted: %s", url)
        return None


async def fetch_coin_image(session, contract_address, chain_id):
    """CoinGecko image URL used when DexScreener has no info.imageUrl."""
    platform = COINGECKO_PLATFORM.get((chain_id or "").lower())
    if not platform:
        logger.info("Unsupported chain: %s", chain_id)
        return None

    url = f"https://api.coingecko.com/api/v3/coins/{platform}/contract/{contract_address}"
    try:
        async with session.get(url) as response:
            if response.status == 404:
                logger.info("Token not found on CoinGecko for image: %s", contract_address)
                return None
            if response.status != 200:
                raise RuntimeError(f"CoinGecko API request failed: {response.status} {response.reason}")
            data = await _read_json(response)
        image = (data or {}).get("image") or {}
        return image.get("large") or image.get("small")
    except Exception as exc:
        logger.info("CoinGecko image API error for %s: %s", contract_address, exc)
        return None


async def fetch_ohlc_data(session, network, pool_address, timeframe="hour", limit=100):
    """OHLCV rows from GeckoTerminal. Each row is timestamp/open/high/low/close/volume."""
    url = (
        f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/"
        f"{pool_address}/ohlcv/{timeframe}?limit={limit}"
    )
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"GeckoTerminal API error: {response.status} {response.reason}")
            data = await _read_json(response)
    except Exception as exc:
        logger.error("Error fetching OHLC data: %s", exc)
        raise

    attributes = ((data or {}).get("data") or {}).get("attributes") or {}
    rows = attributes.get("ohlcv_list") or []
    candles = []
    for item in rows:
        candles.append({
            "timestamp": item[0],
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5] or 0),
        })
    return candles


async def fetch_pool_info(session, network, pool_address):
    """Raw GeckoTerminal pool resource."""
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{pool_address}"
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"GeckoTerminal API error: {response.status} {response.reason}")
            data = await _read_json(response)
        return (data or {}).get("data")
    except Exception as exc:
        logger.error("Error fetching pool info: %s", exc)
        raise


async def search_pools_by_token(session, network, token_address):
    """Pools quoting this token, highest-ranked first."""
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/tokens/{token_address}/pools"
    try:
        logger.info("Searching for pools: %s on %s", token_address, network)
        async with session.get(url) as response:
            if response.status != 200:
                body = await response.text()
                logger.error("GeckoTerminal API error: %s %s", response.status, response.reason)
                logger.error("Error details: %s", body[:300])
                logger.error("Request URL: %s", url)
                if response.status == 404:
                    logger.error("Token %s not found on %s network", token_address, network)
                raise RuntimeError(f"GeckoTerminal API error: {response.status} {response.reason}")
            data = await _read_json(response)
        pools = (data or {}).get("data") or []
        logger.info("Found %s pools for %s on %s", len(pools), token_address, network)
        return pools
    except Exception as exc:
        logger.error("Error searching pools for %s on %s: %s", token_address, network, exc)
        logger.error("Request URL: %s", url)
        raise
