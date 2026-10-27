import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.table import Table
from io import BytesIO
from datetime import datetime
import warnings
import re
import os
import logging
from core.utils import release_memory
from .rank_db import save_previous_rankings, load_previous_rankings

logger = logging.getLogger("crypto_tool.vwap.table_gen")

def calculate_rank_changes(current_rankings: list, previous_rankings: list) -> dict:
    """Calculate rank changes between current and previous rankings."""
    if not previous_rankings:
        return {}

    current_map = {symbol: rank for symbol, rank in current_rankings}
    previous_map = {symbol: rank for symbol, rank in previous_rankings}

    rank_changes = {}
    for symbol in current_map:
        if symbol in previous_map:
            rank_changes[symbol] = previous_map[symbol] - current_map[symbol]

    return rank_changes

def generate_table_image(table_data: str, session_name: str = "UNKNOWN", weight: str = "0.0",
                         last_updated: str = None, footer_text: str = None, interval_str: str = None,
                         next_update: str = None) -> BytesIO:
    """Generate high-definition table image from VWAP scanner text data."""
    parsed_data = parse_table_data(table_data)
    if not parsed_data:
        return generate_error_image("No data available")

    current_rankings = [(row[1], int(row[0])) for row in parsed_data]

    # Parse interval in seconds
    interval_seconds = 300
    if interval_str:
        il = interval_str.lower()
        if 'm' in il:
            interval_seconds = int(float(il.replace('m', ''))) * 60
        elif 'h' in il:
            interval_seconds = int(float(il.replace('h', '')) * 3600)
        elif 's' in il:
            interval_seconds = int(float(il.replace('s', '')))

    previous_rankings = load_previous_rankings(session_name, interval_seconds)
    rank_changes = calculate_rank_changes(current_rankings, previous_rankings)
    save_previous_rankings(current_rankings, session_name, interval_seconds)

    fig, ax = plt.subplots(figsize=(16, 10), facecolor='#ffffff')
    ax.set_facecolor('#ffffff')
    ax.axis('off')

    table = Table(ax, bbox=[0.05, 0.10, 0.9, 0.78])
    table.auto_set_font_size(False)
    table.set_fontsize(10)

    header_color = '#2563eb'
    alt_row_colors = ['#f8fafc', '#f1f5f9']
    text_color = '#1e293b'
    border_color = '#e2e8f0'

    headers = ['Rank', 'Symbol', 'Signal', 'Score', 'Price', 'VWAP', 'Volume', 'RSI', 'MACD', 'Stoch']
    for j, header in enumerate(headers):
        cell = table.add_cell(0, j, width=1/len(headers), height=0.08, text=header,
                             loc='center', facecolor=header_color, edgecolor=border_color)
        cell.get_text().set_color('#ffffff')
        cell.get_text().set_fontweight('bold')
        cell.get_text().set_fontsize(11)

    for i, row in enumerate(parsed_data[:15], 1):
        row_color = alt_row_colors[i % 2]
        for j, (header, value) in enumerate(zip(headers, row)):
            cell_color = row_color
            text_color_for_cell = text_color
            is_bold = False

            if header == 'Signal':
                if 'STRONG BUY' in str(value):
                    text_color_for_cell = '#0f5132'
                    is_bold = True
                elif 'BUY' in str(value):
                    text_color_for_cell = '#22c55e'
                    is_bold = True
                elif 'STRONG SELL' in str(value):
                    text_color_for_cell = '#b91c1c'
                    is_bold = True
                elif 'SELL' in str(value):
                    text_color_for_cell = '#ef4444'
                    is_bold = True

            display_text = str(value)
            if header == 'Rank':
                symbol = row[1]
                if symbol in rank_changes:
                    change = rank_changes[symbol]
                    if change > 0:
                        display_text = f"{value} (▲{change})"
                        text_color_for_cell = '#16a34a'
                    elif change < 0:
                        display_text = f"{value} (▼{abs(change)})"
                        text_color_for_cell = '#dc2626'

            cell = table.add_cell(i, j, width=1/len(headers), height=0.06, text=display_text,
                                 loc='center', facecolor=cell_color, edgecolor=border_color)
            cell.get_text().set_color(text_color_for_cell)
            if is_bold:
                cell.get_text().set_fontweight('bold')
            cell.get_text().set_fontsize(9)

    ax.add_table(table)

    title_text = f"BYBIT FUTURES VWAP SCANNER - UPDATED EVERY {interval_str.upper()}" if interval_str else "BYBIT FUTURES VWAP SCANNER"
    ax.text(0.5, 0.95, title_text, transform=ax.transAxes, fontsize=16, fontweight='bold', color='#1e293b', ha='center', va='top')

    if last_updated and next_update:
        session_text = f"Current Session: {session_name} | Weight: {weight} | Last Updated: {last_updated} | Next Update: {next_update}"
    elif last_updated:
        session_text = f"Current Session: {session_name} | Weight: {weight} | Last Updated: {last_updated}"
    else:
        session_text = f"Current Session: {session_name} | Weight: {weight}"
    ax.text(0.5, 0.92, session_text, transform=ax.transAxes, fontsize=11, color='#64748b', ha='center', va='top')

    if footer_text:
        ax.text(0.5, 0.05, footer_text, transform=ax.transAxes, fontsize=9, color='#94a3b8', ha='center', va='bottom')

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, facecolor='#ffffff', edgecolor='none', bbox_inches='tight')
    buf.seek(0)

    plt.close(fig)
    plt.close('all')
    release_memory()
    return buf

def parse_table_data(table_data: str) -> list:
    """Parse raw table text data into structured tuples."""
    if not isinstance(table_data, str):
        return []

    lines = table_data.split('\n')
    parsed_rows = []

    for line in lines:
        line = line.strip()
        if not line or line.startswith('=') or line.startswith('-') or 'RANK' in line.upper() or 'BYBIT' in line.upper() or 'Session' in line.upper() or 'SYMBOL' in line.upper():
            continue

        parts = line.split()
        if len(parts) < 10 or not parts[0].isdigit():
            continue

        try:
            rank = parts[0]
            symbol = parts[1]

            signal_parts = []
            score_idx = -1
            for j, part in enumerate(parts[2:], 2):
                if part.replace('.', '').replace('-', '').isdigit():
                    score_idx = j
                    break
                signal_parts.append(part)

            signal = re.sub(r'[🔴🟢⚪🔥]\s*', '', ' '.join(signal_parts)).strip()
            score = parts[score_idx] if score_idx > 0 else "N/A"
            price = parts[score_idx + 1] if score_idx + 1 < len(parts) else "N/A"
            vwap = parts[score_idx + 2] if score_idx + 2 < len(parts) else "N/A"
            volume = parts[score_idx + 3] if score_idx + 3 < len(parts) else "N/A"
            rsi = parts[score_idx + 4] if score_idx + 4 < len(parts) else "N/A"
            macd = parts[score_idx + 5] if score_idx + 5 < len(parts) else "N/A"
            stoch = parts[score_idx + 6] if score_idx + 6 < len(parts) else "N/A"

            parsed_rows.append((rank, symbol, signal, score, price, vwap, volume, rsi, macd, stoch))
        except Exception:
            continue

    return parsed_rows

def generate_error_image(error_message: str) -> BytesIO:
    """Generate simple error image."""
    fig, ax = plt.subplots(figsize=(12, 6), facecolor='#ffffff')
    ax.set_facecolor('#ffffff')
    ax.axis('off')

    ax.text(0.5, 0.6, "Error", transform=ax.transAxes, fontsize=24, color='#dc2626', ha='center', va='center', fontweight='bold')
    ax.text(0.5, 0.4, error_message, transform=ax.transAxes, fontsize=14, color='#64748b', ha='center', va='center')
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    ax.text(0.5, 0.1, f"Generated: {timestamp}", transform=ax.transAxes, fontsize=10, color='#94a3b8', ha='center', va='center')

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, facecolor='#ffffff', edgecolor='none')
    buf.seek(0)
    plt.close(fig)
    plt.close('all')
    release_memory()
    return buf
