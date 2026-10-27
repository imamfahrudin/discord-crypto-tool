"""
Database utilities for rank delta tracking in the VWAP scanner.
"""

import sqlite3
import os
import logging
import threading
from config import DB_PATH

db_lock = threading.Lock()
logger = logging.getLogger("crypto_tool.vwap.rank_db")

def init_rankings_table():
    """Ensure the previous_rankings table exists."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS previous_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_name TEXT NOT NULL,
                interval INTEGER DEFAULT 300,
                symbol TEXT NOT NULL,
                rank INTEGER NOT NULL,
                scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_name, interval, symbol, scan_time)
            )
        ''')
        conn.commit()
        conn.close()

def save_previous_rankings(rankings, session_name: str, interval: int = 300):
    """Save rankings and prune scans older than the latest two."""
    init_rankings_table()
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                DELETE FROM previous_rankings 
                WHERE session_name = ? AND interval = ? 
                AND scan_time < (
                    SELECT MAX(scan_time) 
                    FROM previous_rankings 
                    WHERE session_name = ? AND interval = ?
                )
            ''', (session_name, interval, session_name, interval))

            for symbol, rank in rankings:
                cursor.execute('''
                    INSERT INTO previous_rankings (session_name, interval, symbol, rank, scan_time)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (session_name, interval, symbol, rank))
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving rankings: {e}")
        finally:
            conn.close()

def load_previous_rankings(session_name: str, interval: int = 300) -> list:
    """Load the second-most recent rankings scan to calculate rank shifts."""
    init_rankings_table()
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT DISTINCT scan_time 
                FROM previous_rankings
                WHERE session_name = ? AND interval = ?
                ORDER BY scan_time DESC
                LIMIT 1 OFFSET 1
            ''', (session_name, interval))

            row = cursor.fetchone()
            if not row:
                return []

            previous_scan_time = row[0]
            cursor.execute('''
                SELECT symbol, rank FROM previous_rankings
                WHERE session_name = ? AND interval = ? AND scan_time = ?
                ORDER BY rank
            ''', (session_name, interval, previous_scan_time))

            return [(symbol, rank) for symbol, rank in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error loading previous rankings: {e}")
            return []
        finally:
            conn.close()
