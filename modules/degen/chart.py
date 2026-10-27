"""
Candlestick chart for degen token lookups.

Uses the matplotlib / mplfinance already installed for the screening module.
Charts are drawn on DegenCog's single worker thread so they do not share
screening's executor.
"""

import logging
import warnings
from datetime import datetime, timezone
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from core.utils import release_memory

logger = logging.getLogger("crypto_tool.degen.chart")


def generate_candlestick_chart(ohlc_data, token_name, symbol, timeframe, contract_address=None, network=None):
    """
    Return a PNG BytesIO of the candlestick chart, or None on failure.
    token_name is accepted so the call matches the original Node helper; the
    title uses the symbol, the same way the Node chart did.
    """
    del token_name  # kept in the signature for call-site parity
    fig = None
    try:
        df = pd.DataFrame(ohlc_data)
        if df.empty:
            return None

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df = df.set_index("timestamp").sort_index()
        df = df.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        })

        mc = mpf.make_marketcolors(
            up="#00D4AA", down="#FF6B6B",
            edge="inherit",
            wick={"up": "#00D4AA", "down": "#FF6B6B"},
            volume={"up": "#00D4AA", "down": "#FF6B6B"},
            alpha=0.9,
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            gridcolor="#e0e0e0",
            gridstyle=":",
            y_on_right=True,
            facecolor="#ffffff",
            edgecolor="#000000",
            figcolor="#ffffff",
            gridaxis="both",
        )

        fig, axes = mpf.plot(
            df,
            type="candle",
            style=style,
            volume=True,
            volume_panel=1,
            panel_ratios=(7, 1),
            ylabel="Price",
            ylabel_lower="Volume",
            figsize=(24, 12),
            scale_padding=0.8,
            scale_width_adjustment=dict(candle=0.8),
            returnfig=True,
            warn_too_much_data=500,
        )

        ax = axes[0]
        if len(axes) > 1:
            volume_ax = axes[1]
            for collection in volume_ax.collections:
                collection.set_alpha(0.7)
            for patch in volume_ax.patches:
                patch.set_alpha(0.7)
            volume_ax.set_facecolor("#ffffff")
            volume_ax.grid(True, alpha=0.2, linestyle=":", linewidth=0.5)

        for axis in axes:
            for spine in axis.spines.values():
                spine.set_edgecolor("black")
                spine.set_linewidth(1.5)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        title_lines = [f"{symbol} • {str(timeframe).upper()} • {timestamp}"]
        if contract_address and network:
            title_lines.append(f"{contract_address} • {str(network).upper()}")
        elif contract_address:
            title_lines.append(str(contract_address))
        elif network:
            title_lines.append(str(network).upper())

        ax.set_title("\n".join(title_lines), color="#212121", fontsize=16, pad=20, fontweight="bold")
        ax.grid(True, alpha=0.3, linestyle=":", linewidth=0.5)
        ax.set_facecolor("#ffffff")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            fig.tight_layout()

        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=200, facecolor="#ffffff", edgecolor="none", bbox_inches="tight")
        buf.seek(0)
        return buf
    except Exception as exc:
        logger.error("Error generating degen chart: %s", exc)
        return None
    finally:
        if fig is not None:
            plt.close(fig)
        release_memory()
