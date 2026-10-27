import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import time
import os
import json
from config import CACHE_DIR

LOG_PREFIX = "[bybit_data]"

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
CACHE_FILE = os.path.join(CACHE_DIR, 'bybit_pairs_cache.json')
CACHE_EXPIRY = 3600  # 1 hour

BYBIT_URLS = [
    'https://api.bybit.com/v5/market/instruments-info?category=linear',
    'https://api.bybitglobal.com/v5/market/instruments-info?category=linear'
]

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
    for url in BYBIT_URLS:
        cursor = ""
        page_count = 0
        while True:
            page_count += 1
            params = {
                'category': 'linear',
                'status': 'Trading',
                'limit': 1000
            }
            if cursor:
                params['cursor'] = cursor

            try:
                resp = _SESSION.get(url, params=params, timeout=(10, 30))
                resp.raise_for_status()
                data = resp.json()
                if data.get('retCode') != 0:
                    break
                result = data.get('result', {}) or {}
                symbol_list = result.get('list', []) or []
                if not symbol_list:
                    break
                for s in symbol_list:
                    if isinstance(s, dict):
                        sym = s.get('symbol', '')
                        status = s.get('status', '')
                        if sym.endswith('USDT') and status.lower() == 'trading':
                            if sym not in pairs:
                                pairs.append(sym)
                next_cursor = result.get('nextPageCursor')
                if not next_cursor:
                    break
                cursor = next_cursor
                time.sleep(0.1)
            except Exception as e:
                print(f"{LOG_PREFIX} ❌ Error fetching page {page_count} from {url}: {e}")
                break

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
    s = (symbol or '').strip().upper().replace('-', '').replace('/', '')
    if not s.endswith('USDT'):
        s = s + 'USDT'
    return s

def pair_exists(symbol: str) -> bool:
    symbol = normalize_symbol(symbol)
    pairs = get_all_pairs()
    if symbol in pairs:
        return True
    # Refresh cache once
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
        '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
        '1h': '60', '2h': '120', '4h': '240', '6h': '360',
        '1d': 'D', '1w': 'W', '1M': 'M'
    }
    timeframe = timeframe.lower()
    if timeframe not in tf_map:
        raise ValueError(f"Timeframe {timeframe} tidak valid. Pilih salah satu dari {list(tf_map.keys())}")
    interval = tf_map[timeframe]
    if not pair_exists(symbol):
        raise ValueError(f"Pasangan {symbol} tidak tersedia di Bybit Futures (linear).")

    for domain in ['api.bybit.com', 'api.bybitglobal.com']:
        for attempt in range(3):
            try:
                url = f"https://{domain}/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
                resp = _SESSION.get(url, timeout=(15, 45))
                resp.raise_for_status()
                data = resp.json()
                result = data.get('result', {}) or {}
                ohlc_list = result.get('list', []) or []
                if isinstance(ohlc_list, list) and len(ohlc_list) > 0:
                    df = pd.DataFrame(ohlc_list, columns=['open_time','open','high','low','close','volume','turnover'])
                    df = df.astype({'open':'float','high':'float','low':'float','close':'float','volume':'float'})
                    df = df.iloc[::-1].reset_index(drop=True)
                    try:
                        df['open_time'] = pd.to_datetime(df['open_time'].astype('int64'), unit='ms')
                    except Exception:
                        pass
                    return df
            except Exception:
                time.sleep(1)
                break
    raise ValueError(f"Tidak ada data candle untuk {symbol} {timeframe}")

def get_last_price_from_rest(symbol: str):
    symbol = normalize_symbol(symbol)
    for domain in ['api.bybit.com', 'api.bybitglobal.com']:
        for attempt in range(3):
            try:
                url = f"https://{domain}/v5/market/tickers?category=linear&symbol={symbol}"
                resp = _SESSION.get(url, timeout=(8, 15))
                resp.raise_for_status()
                data = resp.json()
                if data.get('retCode') != 0:
                    break
                result = data.get('result', {}) or {}
                ticker_list = result.get('list', []) or []
                if ticker_list:
                    tick = ticker_list[0]
                    last_price = float(tick.get('lastPrice', tick.get('price', 0) or 0))
                    mark_price = float(tick.get('markPrice', last_price))
                    final = mark_price if abs(mark_price - last_price) < 5 else last_price
                    return float(final)
            except Exception:
                time.sleep(0.5)
                break
    return None
