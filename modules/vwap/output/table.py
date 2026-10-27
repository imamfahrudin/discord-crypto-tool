def signal_icon(signal):
    return {
        "STRONG BUY": "🟢🔥",
        "BUY": "🟢",
        "NEUTRAL": "⚪",
        "SELL": "🔴",
        "STRONG SELL": "🔴🔥"
    }.get(signal, "")

def render_table(rows, session, weight):
    lines = []
    lines.append("BYBIT FUTURES VWAP SESSION SCANNER")
    lines.append(f"Session : {session} | Weight : {weight}")
    lines.append("=" * 150)
    lines.append(
        "RANK  SYMBOL          SIGNAL               SCORE    PRICE       VWAP        VOL(M)   RSI    MACD     STOCH"
    )
    lines.append("-" * 150)

    for i, r in enumerate(rows, 1):
        sig = f"{signal_icon(r['signal'])} {r['signal']}"
        lines.append(
            f"{i:<5} {r['symbol']:<14} {sig:<20} "
            f"{r['score']:<8.2f} {r['price']:<11.6g} {r['vwap']:<11.6g} "
            f"{r['volume_m']:<7.2f} {r['rsi']:<6.1f} {r['macd']:<7.2f} {r['stoch']:<6.1f}"
        )

    return "\n".join(lines)
