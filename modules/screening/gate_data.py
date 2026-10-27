import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
import os
import json
from config import CACHE_DIR

LOG_PREFIX = "[gate_data]"

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
CACHE_FILE = os.path.join(CACHE_DIR, 'gate_pairs_cache.json')
CACHE_EXPIRY = 3600

GATE_BASE_URL = 'https://api.gateio.ws/api/v4'

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
        url = f"{GATE_BASE_URL}/futures/usdt/contracts"
        resp = _SESSION.get(url, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        for contract in data:
            if isinstance(contract, dict):
                name = contract.get('name', '')
                if name.endswith('_USDT') and contract.get('type') == 'direct':
                    symbol = name.replace('_', '')
                    if symbol not in pairs:
                        pairs.append(symbol)
    except Exception as e:
        print(f"{LOG_PREFIX} ❌ Error fetching pairs from Gate.io: {e}")

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
    if s.endswith('USDT') and '_' not in s:
        base = s[:-4]
        s = f"{base}_USDT"
    return s

def pair_exists(symbol: str) -> bool:
    symbol_normalized = normalize_symbol(symbol)
    symbol_no_underscore = symbol_normalized.replace('_', '')
    pairs = get_all_pairs()
    if symbol_no_underscore in pairs:
        return True
    for attempt in range(2):
        try:
            pairs = get_all_pairs(force_refresh=True)
            return symbol_no_underscore in pairs
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
    symbol_normalized = normalize_symbol(symbol)
    tf_map = {
        '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
        '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '12h': '12h',
        '1d': '1d', '1w': '1w', '1M': '1M'
    }
    interval = tf_map.get(timeframe.lower())
    if not interval:
        raise ValueError(f"Invalid timeframe {timeframe}")

    if timeframe.lower() == '1d':
        limit = min(limit, 365)
    elif timeframe.lower() in ['1w']:
        limit = min(limit, 200)

    url = f"{GATE_BASE_URL}/futures/usdt/candlesticks"
    params = {
        'contract': symbol_normalized,
        'interval': interval,
        'limit': limit
    }

    try:
        resp = _SESSION.get(url, params=params, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise Exception(f"No candle data for {symbol_normalized}")

        df = pd.DataFrame(data)
        df = df.rename(columns={'t': 'timestamp', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
        for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df = df.sort_values('timestamp', ascending=True).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"{LOG_PREFIX} ❌ Error fetching OHLC data: {e}")
        raise

def get_last_price_from_rest(symbol: str):
    symbol_normalized = normalize_symbol(symbol)
    try:
        url = f"{GATE_BASE_URL}/futures/usdt/contracts/{symbol_normalized}"
        resp = _SESSION.get(url, timeout=(10, 30))
        resp.raise_for_status()
        data = resp.json()
        return float(data.get('last_price', 0))
    except Exception:
        return None
