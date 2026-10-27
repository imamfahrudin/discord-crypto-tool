import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
import os
import json
from config import CACHE_DIR

LOG_PREFIX = "[bitget_data]"

def _create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20,
        pool_block=False
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.timeout = (10, 30)
    return session

_SESSION = _create_session()
_PAIRS_CACHE = None
CACHE_FILE = os.path.join(CACHE_DIR, 'bitget_pairs_cache.json')
CACHE_EXPIRY = 3600

BITGET_BASE_URL = 'https://api.bitget.com'

def _load_pairs_from_disk():
    try:
        if os.path.exists(CACHE_FILE):
            if os.path.isdir(CACHE_FILE):
                os.rmdir(CACHE_FILE)
                return None
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'pairs' in data and 'timestamp' in data:
                    if time.time() - data['timestamp'] < CACHE_EXPIRY:
                        return data['pairs']
    except Exception as e:
        print(f"{LOG_PREFIX} 📂 Error loading cache from disk: {e}")
    return None

def get_all_pairs(force_refresh=False):
    global _PAIRS_CACHE
    if _PAIRS_CACHE is not None and not force_refresh:
        return _PAIRS_CACHE
    disk = _load_pairs_from_disk()
    if disk and not force_refresh:
        _PAIRS_CACHE = disk
        return _PAIRS_CACHE

    pairs = []
    try:
        url = f"{BITGET_BASE_URL}/api/v2/mix/market/contracts"
        params = {'productType': 'USDT-FUTURES'}
        resp = _SESSION.get(url, params=params, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == '00000':
            symbols = data.get('data', [])
            for symbol_info in symbols:
                if isinstance(symbol_info, dict):
                    symbol = symbol_info.get('symbol', '')
                    quote_coin = symbol_info.get('quoteCoin', '')
                    if quote_coin == 'USDT' and symbol.endswith('USDT'):
                        if symbol not in pairs:
                            pairs.append(symbol)
    except Exception as e:
        print(f"{LOG_PREFIX} ❌ Error fetching pairs from Bitget: {e}")

    if pairs:
        _PAIRS_CACHE = pairs
        try:
            cache_data = {'pairs': pairs, 'timestamp': time.time()}
            with open(CACHE_FILE, 'w') as f:
                json.dump(cache_data, f)
        except Exception as e:
            print(f"{LOG_PREFIX} ❌ Error saving cache to disk: {e}")
        return _PAIRS_CACHE

    _PAIRS_CACHE = disk or []
    return _PAIRS_CACHE

def normalize_symbol(symbol: str) -> str:
    s = (symbol or '').strip().upper().replace('-', '').replace('/', '').replace('_', '')
    if not s.endswith('USDT'):
        s = s + 'USDT'
    return s

def pair_exists(symbol: str) -> bool:
    symbol = normalize_symbol(symbol)
    pairs = get_all_pairs()
    if symbol in pairs:
        return True
    for attempt in range(2):
        try:
            pairs = get_all_pairs(force_refresh=True)
            return symbol in pairs
        except Exception:
            time.sleep(1)
    return False

# OHLC Data Cache
_OHLC_CACHE = {}
OHLC_CACHE_TTL = 300
OHLC_CACHE_MAX_ENTRIES = 100

def fetch_ohlc_cached(symbol: str, timeframe: str, limit: int = 500):
    key = (symbol, timeframe)
    now = time.time()
    if key in _OHLC_CACHE:
        df, cached_time = _OHLC_CACHE[key]
        if now - cached_time < OHLC_CACHE_TTL and len(df) >= limit:
            return df

    df = fetch_ohlc(symbol, timeframe, limit)

    expired = [k for k, (_, ts) in _OHLC_CACHE.items() if now - ts >= OHLC_CACHE_TTL]
    for k in expired:
        del _OHLC_CACHE[k]
    if len(_OHLC_CACHE) >= OHLC_CACHE_MAX_ENTRIES:
        oldest_key = min(_OHLC_CACHE, key=lambda k: _OHLC_CACHE[k][1])
        del _OHLC_CACHE[oldest_key]

    _OHLC_CACHE[key] = (df, now)
    return df

def fetch_ohlc(symbol: str, timeframe: str, limit: int = 500):
    symbol = normalize_symbol(symbol)
    tf_map = {
        '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
        '1h': '1H', '2h': '2H', '4h': '4H', '6h': '6H', '12h': '12H',
        '1d': '1D', '1w': '1W', '1M': '1M'
    }
    interval = tf_map.get(timeframe.lower())
    if not interval:
        raise ValueError(f"Invalid timeframe {timeframe}")

    if timeframe.lower() == '1d':
        limit = min(limit, 90)
    elif timeframe.lower() in ['1w', '1M']:
        limit = min(limit, 100)

    current_time = int(time.time() * 1000)
    interval_ms = {
        '1m': 60000, '3m': 180000, '5m': 300000, '15m': 900000, '30m': 1800000,
        '1H': 3600000, '2H': 7200000, '4H': 14400000, '6H': 21600000, '12H': 43200000,
        '1D': 86400000, '1W': 604800000, '1M': 2592000000
    }
    duration_ms = interval_ms.get(interval, 3600000) * limit
    oldest_time = current_time - duration_ms

    url = f"{BITGET_BASE_URL}/api/v2/mix/market/candles"
    params = {
        'symbol': symbol,
        'productType': 'USDT-FUTURES',
        'granularity': interval,
        'startTime': str(oldest_time),
        'endTime': str(current_time)
    }

    try:
        resp = _SESSION.get(url, params=params, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') != '00000':
            raise Exception(f"Bitget API error: {data.get('msg', 'Unknown error')}")
        candles = data.get('data', [])
        if not candles:
            raise Exception(f"No candle data for {symbol}")

        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'quoteVol'])
        for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.sort_values('timestamp', ascending=True).reset_index(drop=True)
        df = df.drop('quoteVol', axis=1)
        return df
    except Exception as e:
        print(f"{LOG_PREFIX} ❌ Error fetching OHLC data: {e}")
        raise

def get_last_price_from_rest(symbol: str):
    symbol = normalize_symbol(symbol)
    try:
        url = f"{BITGET_BASE_URL}/api/v2/mix/market/ticker"
        params = {'symbol': symbol, 'productType': 'USDT-FUTURES'}
        resp = _SESSION.get(url, params=params, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == '00000':
            ticker_list = data.get('data', [])
            if ticker_list:
                return float(ticker_list[0].get('lastPr', 0))
    except Exception:
        pass
    return None
