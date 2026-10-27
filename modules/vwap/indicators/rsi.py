def rsi(closes, period=14):
    """Pure-python RSI to avoid loading heavy numpy array overhead."""
    if len(closes) < period + 1:
        return 50.0
    window = [closes[i] - closes[i - 1] for i in range(1, len(closes))][-period:]
    ag = sum(d for d in window if d > 0) / len(window)
    al = sum(-d for d in window if d < 0) / len(window)
    if al == 0:
        return 100.0
    return round(100.0 - (100.0 / (1.0 + ag / al)), 2)
