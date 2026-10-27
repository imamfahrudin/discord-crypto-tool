"""
Exchange Factory - Abstracts data fetching from different exchanges.
Supports: Bybit, Binance, Bitget, Gate.io
"""

from . import bybit_data
from . import binance_data
from . import bitget_data
from . import gate_data

LOG_PREFIX = "[exchange_factory]"

def get_exchange_module(exchange: str):
    """
    Get the appropriate exchange data module based on exchange name.
    """
    exchange = (exchange or '').lower().strip()
    if exchange == 'binance':
        return binance_data
    elif exchange == 'bybit':
        return bybit_data
    elif exchange == 'bitget':
        return bitget_data
    elif exchange in ('gateio', 'gate'):
        return gate_data
    else:
        return bybit_data

def fetch_ohlc(symbol: str, timeframe: str, exchange: str = 'bybit', limit: int = 500):
    """Fetch OHLC data from specified exchange with caching."""
    module = get_exchange_module(exchange)
    return module.fetch_ohlc_cached(symbol, timeframe, limit)

def normalize_symbol(symbol: str, exchange: str = 'bybit') -> str:
    """Normalize symbol to exchange format."""
    module = get_exchange_module(exchange)
    return module.normalize_symbol(symbol)

def pair_exists(symbol: str, exchange: str = 'bybit') -> bool:
    """Check if trading pair exists on the exchange."""
    module = get_exchange_module(exchange)
    return module.pair_exists(symbol)

def get_all_pairs(exchange: str = 'bybit', force_refresh: bool = False):
    """Get all available trading pairs from exchange."""
    module = get_exchange_module(exchange)
    return module.get_all_pairs(force_refresh)

def get_last_price_from_rest(symbol: str, exchange: str = 'bybit'):
    """Get last price for a symbol from exchange REST API."""
    module = get_exchange_module(exchange)
    return module.get_last_price_from_rest(symbol)
