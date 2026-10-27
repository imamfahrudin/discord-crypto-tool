"""
Standalone test script for VWAP table image generation and ranking tracking.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.vwap.table_generator import generate_table_image
from datetime import datetime

def test_vwap():
    print(f"\n==================================================")
    print(f"Testing VWAP Scanner Table Generator")
    print(f"==================================================")

    sample_table_data = """
================================================================================
BYBIT FUTURES VWAP SCANNER
================================================================================
Session : LONDON | Weight : 1.0
================================================================================
RANK  SYMBOL          SIGNAL               SCORE    PRICE       VWAP        VOL(M)   RSI    MACD     STOCH
--------------------------------------------------------------------------------
1     BTCUSDT         🟢🔥 STRONG BUY      94.50    67500       66800       1450.2   62.4   0.0035   75.2
2     ETHUSDT         🟢 BUY               45.20    3550        3510        890.5    58.1   0.0012   68.4
3     SOLUSDT         ⚪ NEUTRAL           12.10    182.4       181.8       450.1    49.5   0.0001   51.0
4     DOGEUSDT        🔴 SELL              -32.40   0.145       0.149       210.0    38.2   -0.0008  33.5
5     ADAUSDT         🔴🔥 STRONG SELL     -88.90   0.420       0.445       180.2    27.8   -0.0022  18.1
================================================================================
"""

    buf = generate_table_image(
        table_data=sample_table_data,
        session_name="LONDON",
        weight="1.0",
        last_updated=datetime.now().strftime("%H:%M:%S WIB"),
        footer_text="© Crypto Tool Test",
        interval_str="5m",
        next_update="In 5m"
    )

    out_file = "test_vwap_table.png"
    with open(out_file, "wb") as f:
        f.write(buf.getvalue())
    print(f"✅ Table image successfully generated and saved to {out_file} ({len(buf.getvalue())} bytes)")

if __name__ == "__main__":
    test_vwap()
