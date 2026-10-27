def ema(data, p):
    k = 2 / (p + 1)
    e = data[0]
    for x in data[1:]:
        e = x * k + e * (1 - k)
    return e

def macd_hist(closes):
    """Pure-python MACD histogram."""
    if len(closes) < 26:
        return 0.0
    m = ema(closes[-26:], 12) - ema(closes[-26:], 26)
    s = ema(closes[-9:], 9)
    return round(m - s, 4)
