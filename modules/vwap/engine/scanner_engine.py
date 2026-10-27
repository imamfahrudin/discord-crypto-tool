from config import STRONG_SCORE, BUY_SCORE, SELL_SCORE, STRONG_SELL_SCORE

def classify_signal(score: float) -> str:
    if score >= STRONG_SCORE:
        return "STRONG BUY"
    if score >= BUY_SCORE:
        return "BUY"
    if score <= STRONG_SELL_SCORE:
        return "STRONG SELL"
    if score <= SELL_SCORE:
        return "SELL"
    return "NEUTRAL"

def scan(market, session_name, weight):
    ranked = []
    for m in market:
        volume_factor = min((m["volume_m"] ** 0.5), 5)
        score = (
            m["vwap_dev"] *
            volume_factor *
            10 *
            weight
        )
        signal = classify_signal(score)
        ranked.append({
            **m,
            "score": round(score, 2),
            "signal": signal
        })

    # Sort absolute score descending
    ranked.sort(key=lambda x: abs(x["score"]), reverse=True)
    return ranked
