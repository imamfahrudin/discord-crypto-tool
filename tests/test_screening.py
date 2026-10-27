"""
Standalone test script for Screening module logic and chart rendering.
Can be executed locally without running the Discord bot.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.screening.signal_logic import generate_trade_plan
from modules.screening.chart_generator import generate_chart_with_setup, generate_neutral_chart
from modules.screening.exchange_factory import normalize_symbol

def test_screening(symbol="BTC", timeframe="1h"):
    print(f"\n==================================================")
    print(f"Testing Screening Tool: {symbol} {timeframe}")
    print(f"==================================================")

    symbol_norm = normalize_symbol(symbol, 'bybit')
    print(f"Normalized symbol: {symbol_norm}")

    data = generate_trade_plan(symbol_norm, timeframe, 'bybit', return_dict=True)
    direction = data.get('direction', 'neutral')
    print(f"✅ Direction: {direction}")
    print(f"✅ Confidence: {data.get('confidence')}% ({data.get('confidence_level')})")
    print(f"✅ Entry: {data.get('entry')} | SL: {data.get('stop_loss')} | TP1: {data.get('tp1')} | TP2: {data.get('tp2')}")

    if direction == 'neutral':
        chart_buf = generate_neutral_chart(
            df=data['df'], symbol=symbol_norm, timeframe=timeframe,
            current_price=data.get('current_price')
        )
    else:
        chart_buf = generate_chart_with_setup(
            df=data['df'], symbol=symbol_norm, timeframe=timeframe,
            direction=direction, entry_price=data.get('entry'),
            stop_loss=data.get('stop_loss'), tp1=data.get('tp1'), tp2=data.get('tp2'),
            current_price=data.get('current_price'), confidence=data.get('confidence')
        )

    out_file = "test_screening_output.png"
    with open(out_file, "wb") as f:
        f.write(chart_buf.getvalue())
    print(f"✅ Chart saved to {out_file} ({len(chart_buf.getvalue())} bytes)")

if __name__ == "__main__":
    test_screening()
