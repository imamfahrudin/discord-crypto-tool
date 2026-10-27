def classify_signal(score):
    if score >= 40:
        return "STRONG BUY"
    elif score >= 15:
        return "BUY"
    elif score <= -40:
        return "STRONG SELL"
    elif score <= -15:
        return "SELL"
    else:
        return "NEUTRAL"
