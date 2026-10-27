def compute_score(price, vwap, rsi, macd, stoch, volume):
    score = 0.0

    # 1. VWAP distance
    vwap_dist = (price - vwap) / vwap * 100
    score += vwap_dist * 1.5

    # 2. RSI contribution
    if rsi > 70:
        score -= 1
    elif rsi > 55:
        score += 1
    elif rsi < 30:
        score += 1
    elif rsi < 45:
        score -= 1

    # 3. MACD histogram
    score += macd * 2

    # 4. Stochastic
    if stoch > 80:
        score -= 0.5
    elif stoch < 20:
        score += 0.5

    # 5. Volume
    if volume == "High":
        score *= 1.1

    return round(score * 10, 2)
