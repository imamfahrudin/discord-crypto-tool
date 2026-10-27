def stochastic(h, l, c, p=14):
    """Pure-python Stochastic oscillator."""
    if len(c) < p:
        return 50.0

    hh = max(h[-p:])
    ll = min(l[-p:])
    diff = hh - ll

    if diff == 0:
        return 50.0

    k = ((c[-1] - ll) / diff) * 100
    return round(k, 2)
