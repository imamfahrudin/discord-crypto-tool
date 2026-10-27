def calculate_vwap(candles):
    """Calculate Volume Weighted Average Price (VWAP) from candle dictionaries."""
    pv = vol = 0
    for c in candles:
        tp = (c["high"] + c["low"] + c["close"]) / 3
        pv += tp * c["volume"]
        vol += c["volume"]
    return round(pv / vol, 6) if vol else None
