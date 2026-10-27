import matplotlib
matplotlib.use('Agg')
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from io import BytesIO
from datetime import datetime
import warnings
from core.utils import release_memory

def get_confidence_color(confidence: float) -> str:
    """Get color based on confidence level."""
    if confidence >= 90:
        return '#00D4AA'
    elif confidence >= 80:
        return '#00C896'
    elif confidence >= 70:
        return '#00BC82'
    elif confidence >= 60:
        return '#8BC34A'
    else:
        return '#FFD93D'

def generate_chart_with_setup(df: pd.DataFrame, 
                              symbol: str, 
                              timeframe: str,
                              direction: str,
                              entry_price: float = None,
                              stop_loss: float = None,
                              tp1: float = None,
                              tp2: float = None,
                              ema13: pd.Series = None,
                              ema21: pd.Series = None,
                              fvg_zones: list = None,
                              ob_high: float = None,
                              ob_low: float = None,
                              current_price: float = None,
                              ema_short: int = 13,
                              ema_long: int = 21,
                              exchange: str = 'bybit',
                              confidence: float = None) -> BytesIO:
    """Generate candlestick chart with position setup overlay."""
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'open_time' in df.columns:
            df = df.set_index('open_time')
        else:
            df.index = pd.to_datetime(df.index)

    df_plot = df.tail(50).copy()

    add_plots = []
    if ema13 is not None:
        add_plots.append(mpf.make_addplot(ema13.tail(50), color='#00BFFF', width=2, label=f'EMA {ema_short}'))
    if ema21 is not None:
        add_plots.append(mpf.make_addplot(ema21.tail(50), color='#FF6B9D', width=2, label=f'EMA {ema_long}'))

    mc = mpf.make_marketcolors(
        up='#00D4AA', down='#FF6B6B',
        edge='inherit',
        wick={'up':'#00D4AA', 'down':'#FF6B6B'},
        volume={'up':'#00D4AA', 'down':'#FF6B6B'},
        alpha=0.9
    )

    s = mpf.make_mpf_style(
        marketcolors=mc,
        gridcolor='#e0e0e0',
        gridstyle=':',
        y_on_right=True,
        facecolor='#ffffff',
        edgecolor='#000000',
        figcolor='#ffffff',
        gridaxis='both'
    )

    plot_kwargs = {
        'type': 'candle',
        'style': s,
        'volume': True,
        'volume_panel': 1,
        'panel_ratios': (7, 1),
        'ylabel': 'Price',
        'ylabel_lower': 'Volume',
        'figsize': (12, 8),
        'returnfig': True,
        'warn_too_much_data': 200
    }

    if len(add_plots) > 0:
        plot_kwargs['addplot'] = add_plots

    fig, axes = mpf.plot(df_plot, **plot_kwargs)
    ax = axes[0]

    if len(axes) > 1:
        volume_ax = axes[1]
        for collection in volume_ax.collections:
            collection.set_alpha(0.7)
        for patch in volume_ax.patches:
            patch.set_alpha(0.7)
        volume_ax.set_facecolor('#ffffff')
        volume_ax.grid(True, alpha=0.2, linestyle=':', linewidth=0.5)

    for axis in axes:
        for spine in axis.spines.values():
            spine.set_edgecolor('black')
            spine.set_linewidth(1.5)

    y_min, y_max = ax.get_ylim()
    x_min, x_max = ax.get_xlim()

    x_range = x_max - x_min
    ax.set_xlim(x_min - x_range * 0.05, x_max + x_range * 0.15)
    x_min, x_max = ax.get_xlim()

    if direction != 'neutral' and entry_price and stop_loss:
        ax.axhline(y=entry_price, color='#00BFFF', linestyle='--', linewidth=2.5, alpha=0.9)
        ax.axhline(y=stop_loss, color='#FF6B6B', linestyle='--', linewidth=2.5, alpha=0.9)

        if tp1:
            ax.axhline(y=tp1, color='#00D4AA', linestyle='--', linewidth=2, alpha=0.8)
        if tp2:
            ax.axhline(y=tp2, color='#00F5A0', linestyle='--', linewidth=2.5, alpha=0.9)

        block_width = (x_max - x_min) * 0.08
        block_start = x_max - block_width * 1.3
        block_end = x_max - block_width * 0.3

        if direction == 'long':
            rect_risk = patches.Rectangle(
                (block_start, stop_loss), block_end - block_start, entry_price - stop_loss,
                linewidth=2, edgecolor='#FF6B6B', facecolor='#FF6B6B', alpha=0.3
            )
            ax.add_patch(rect_risk)
            if tp2:
                rect_reward = patches.Rectangle(
                    (block_start, entry_price), block_end - block_start, tp2 - entry_price,
                    linewidth=2, edgecolor='#00D4AA', facecolor='#00D4AA', alpha=0.3
                )
                ax.add_patch(rect_reward)
                rr_ratio = abs(tp2 - entry_price) / max(abs(entry_price - stop_loss), 1e-8)
                mid_y = (entry_price + tp2) / 2
                ax.text(block_start + (block_end - block_start) / 2, mid_y, f'{rr_ratio:.1f}R',
                       fontsize=12, fontweight='bold', color='white', ha='center', va='center',
                       bbox=dict(boxstyle='round,pad=0.4', facecolor='#00D4AA', edgecolor='white', alpha=0.9))
        else:
            rect_risk = patches.Rectangle(
                (block_start, entry_price), block_end - block_start, stop_loss - entry_price,
                linewidth=2, edgecolor='#FF6B6B', facecolor='#FF6B6B', alpha=0.3
            )
            ax.add_patch(rect_risk)
            if tp2:
                rect_reward = patches.Rectangle(
                    (block_start, tp2), block_end - block_start, entry_price - tp2,
                    linewidth=2, edgecolor='#00D4AA', facecolor='#00D4AA', alpha=0.3
                )
                ax.add_patch(rect_reward)
                rr_ratio = abs(entry_price - tp2) / max(abs(stop_loss - entry_price), 1e-8)
                mid_y = (tp2 + entry_price) / 2
                ax.text(block_start + (block_end - block_start) / 2, mid_y, f'{rr_ratio:.1f}R',
                       fontsize=12, fontweight='bold', color='white', ha='center', va='center',
                       bbox=dict(boxstyle='round,pad=0.4', facecolor='#00D4AA', edgecolor='white', alpha=0.9))

    if fvg_zones:
        for fvg in fvg_zones[-5:]:
            fvg_type = fvg.get('type', '')
            fvg_high = fvg.get('high')
            fvg_low = fvg.get('low')
            if fvg_high and fvg_low:
                color = '#FFD93D' if fvg_type == 'Bullish' else '#A855F7'
                ax.fill_between([x_min, x_max], fvg_low, fvg_high, color=color, alpha=0.15)
                mid_y = (fvg_high + fvg_low) / 2
                ax.text(x_max + (x_max - x_min) * 0.02, mid_y, f'FVG {fvg_type[:4]}', 
                       fontsize=9, color=color, alpha=0.9, ha='left', va='center',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffffff', edgecolor=color, alpha=0.8))

    if ob_high:
        ax.axhline(y=ob_high, color='#FFD93D', linestyle=':', linewidth=2, alpha=0.7)
    if ob_low:
        ax.axhline(y=ob_low, color='#A855F7', linestyle=':', linewidth=2, alpha=0.7)

    if current_price:
        ax.axhline(y=current_price, color='#FFD93D', linestyle='-', linewidth=2, alpha=0.8)
        ax.text(x_min + (x_max - x_min) * 0.25, current_price, f'Current: {current_price:.6f}', 
               fontsize=13, color='#FFD93D', alpha=0.9, ha='center', va='center',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='#000000', edgecolor='#FFD93D', alpha=0.9))

    if direction != 'neutral' and entry_price and stop_loss:
        center_x = x_min + (x_max - x_min) * 0.5
        ax.text(center_x, entry_price, f'Limit: {entry_price:.6f}', 
               fontsize=13, color='#00BFFF', alpha=0.9, ha='center', va='center',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='#000000', edgecolor='#00BFFF', alpha=0.9))
        ax.text(center_x, stop_loss, f'SL: {stop_loss:.6f}', 
               fontsize=13, color='#FF6B6B', alpha=0.9, ha='center', va='center',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='#000000', edgecolor='#FF6B6B', alpha=0.9))
        if tp1:
            ax.text(center_x, tp1, f'TP1: {tp1:.6f}', 
                   fontsize=13, color='#00D4AA', alpha=0.9, ha='center', va='center',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='#000000', edgecolor='#00D4AA', alpha=0.9))
        if tp2:
            ax.text(center_x, tp2, f'TP2: {tp2:.6f}', 
                   fontsize=13, color='#00F5A0', alpha=0.9, ha='center', va='center',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='#000000', edgecolor='#00F5A0', alpha=0.9))

    if direction != 'neutral':
        arrow_color = '#00D4AA' if direction == 'long' else '#FF6B6B'
        arrow_symbol = '▲' if direction == 'long' else '▼'
        direction_text = f'{arrow_symbol} {direction.upper()}'
        ax.text(0.02, 0.95, direction_text,
               transform=ax.transAxes, fontsize=14, fontweight='bold', color='#000000',
               ha='left', va='top',
               bbox=dict(boxstyle='round,pad=0.4', facecolor=arrow_color, edgecolor='#000000', linewidth=2, alpha=0.75))
        
        if confidence is not None:
            confidence_text = f'Confidence: {confidence:.1f}%'
            confidence_color = get_confidence_color(confidence)
            ax.text(0.02, 0.87, confidence_text,
                   transform=ax.transAxes, fontsize=14, fontweight='bold', color='#000000',
                   ha='left', va='top',
                   bbox=dict(boxstyle='round,pad=0.4', facecolor=confidence_color, edgecolor='#000000', linewidth=2, alpha=0.75))

    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    exchange_display = exchange.upper() if exchange else 'BYBIT'
    ax.set_title(f'{symbol} • {timeframe.upper()} • {timestamp} • {exchange_display}', 
                color='#212121', fontsize=16, pad=20, fontweight='bold')

    ax.legend(loc='lower left', bbox_to_anchor=(0.0, 0.0), 
             frameon=True, fancybox=True, shadow=True,
             facecolor='#f9f9f9', edgecolor='#cccccc',
             fontsize=10, labelcolor='#212121')

    ax.grid(True, alpha=0.3, linestyle=':', linewidth=0.5)
    ax.set_facecolor('#ffffff')

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=100, facecolor='#ffffff', edgecolor='none', bbox_inches='tight')
    buf.seek(0)

    plt.close(fig)
    plt.close('all')
    release_memory()
    return buf

def generate_neutral_chart(df: pd.DataFrame,
                           symbol: str,
                           timeframe: str,
                           ema13: pd.Series = None,
                           ema21: pd.Series = None,
                           current_price: float = None,
                           ema_short: int = 13,
                           ema_long: int = 21,
                           exchange: str = 'bybit') -> BytesIO:
    """Generate a simple chart for neutral signals."""
    return generate_chart_with_setup(
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        direction='neutral',
        ema13=ema13,
        ema21=ema21,
        current_price=current_price,
        ema_short=ema_short,
        ema_long=ema_long,
        exchange=exchange
    )
