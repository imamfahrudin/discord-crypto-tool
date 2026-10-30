"""
Database manager for SQLite persistence.
Handles active channel scanner states and previous ranking history.
"""

import sqlite3
import threading
import logging
import os
from config import DB_PATH

logger = logging.getLogger("crypto_tool.database")
db_lock = threading.Lock()


def get_connection():
    """Get a SQLite database connection ensuring parent directory exists."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_database():
    """Initialize database tables with migrations if needed."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()

        # 1. channel_states table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_states (
                channel_id INTEGER NOT NULL,
                interval INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                guild_id INTEGER,
                running BOOLEAN NOT NULL DEFAULT 0,
                server_name TEXT,
                channel_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (channel_id, interval)
            )
        ''')

        # 2. previous_rankings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS previous_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                rank INTEGER NOT NULL,
                interval INTEGER DEFAULT 300,
                scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_name, interval, symbol, scan_time)
            )
        ''')

        # Run safe migrations
        try:
            cursor.execute("PRAGMA table_info(channel_states)")
            columns = [c[1] for c in cursor.fetchall()]
            if 'guild_id' not in columns:
                cursor.execute("ALTER TABLE channel_states ADD COLUMN guild_id INTEGER")
                logger.info("Migrated channel_states: added guild_id column")
        except Exception as e:
            logger.warning(f"channel_states migration check: {e}")

        try:
            cursor.execute("PRAGMA table_info(previous_rankings)")
            r_cols = [c[1] for c in cursor.fetchall()]
            if 'interval' not in r_cols:
                cursor.execute("ALTER TABLE previous_rankings ADD COLUMN interval INTEGER DEFAULT 300")
                logger.info("Migrated previous_rankings: added interval column")
        except Exception as e:
            logger.warning(f"previous_rankings migration check: {e}")

        # 3. forex_channel_states — channels where the Forex notifier is running.
        # Kept separate from channel_states so VWAP restore does not treat these
        # rows as live scanner messages.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS forex_channel_states (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER,
                running BOOLEAN NOT NULL DEFAULT 1,
                server_name TEXT,
                channel_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 4. session_notifier_state — the single channel for trading-session
        # alerts. Separate from channel_states (VWAP) and forex_channel_states.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_notifier_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                channel_id INTEGER NOT NULL,
                guild_id INTEGER,
                running BOOLEAN NOT NULL DEFAULT 1,
                server_name TEXT,
                channel_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 5. news_state — Bitcoinist summarizer. One row. channel_id and
        # last_processed stay on this row and are not mixed into VWAP,
        # Forex, or session tables. running=0 keeps the last article date
        # so a later !start news does not repost articles already sent.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                channel_id INTEGER,
                guild_id INTEGER,
                running BOOLEAN NOT NULL DEFAULT 0,
                last_processed TEXT,
                server_name TEXT,
                channel_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {DB_PATH}")


def save_channel_state(channel_id, interval, message_id, running, server_name=None, channel_name=None, guild_id=None):
    """Save or update channel state."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO channel_states 
            (channel_id, interval, message_id, guild_id, running, server_name, channel_name, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (channel_id, interval, message_id, guild_id, running, server_name, channel_name))
        conn.commit()
        conn.close()


def load_channel_states():
    """Load all saved running channel states grouped by channel_id."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT channel_id, interval, message_id, running, server_name, channel_name, guild_id
            FROM channel_states
            WHERE running = 1
        ''')
        rows = cursor.fetchall()
        conn.close()

    states = {}
    for r in rows:
        cid, interval, mid, running, server, channel, gid = r
        if cid not in states:
            states[cid] = {}
        states[cid][interval] = {
            'message_id': mid,
            'running': bool(running),
            'server_name': server,
            'channel_name': channel,
            'guild_id': gid
        }
    return states


def save_forex_channel_state(channel_id, running, server_name=None, channel_name=None, guild_id=None):
    """Save or update a Forex notifier channel."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO forex_channel_states
            (channel_id, guild_id, running, server_name, channel_name, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (channel_id, guild_id, running, server_name, channel_name))
        conn.commit()
        conn.close()


def load_forex_channel_states():
    """Load channels where the Forex notifier was left running."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT channel_id, guild_id, running, server_name, channel_name
            FROM forex_channel_states
            WHERE running = 1
        ''')
        rows = cursor.fetchall()
        conn.close()

    states = {}
    for channel_id, guild_id, running, server_name, channel_name in rows:
        states[channel_id] = {
            'guild_id': guild_id,
            'running': bool(running),
            'server_name': server_name,
            'channel_name': channel_name,
        }
    return states


def save_session_notifier_state(channel_id, running, server_name=None, channel_name=None, guild_id=None):
    """Save the single trading-session notifier channel. Row id is always 1."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO session_notifier_state
            (id, channel_id, guild_id, running, server_name, channel_name, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (channel_id, guild_id, running, server_name, channel_name))
        conn.commit()
        conn.close()


def load_session_notifier_state():
    """Load the session notifier channel when it was left running. None if absent."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT channel_id, guild_id, running, server_name, channel_name
            FROM session_notifier_state
            WHERE id = 1 AND running = 1
        ''')
        row = cursor.fetchone()
        conn.close()

    if row is None:
        return None
    channel_id, guild_id, running, server_name, channel_name = row
    return {
        'channel_id': channel_id,
        'guild_id': guild_id,
        'running': bool(running),
        'server_name': server_name,
        'channel_name': channel_name,
    }


def remove_session_notifier_state():
    """Forget the session notifier channel."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM session_notifier_state WHERE id = 1')
        conn.commit()
        conn.close()


def save_news_state(channel_id, running, last_processed=None, server_name=None, channel_name=None, guild_id=None):
    """Save the Bitcoinist news channel and the last processed article time.

    The row id is always 1. ``last_processed`` is an ISO-8601 string or None.
    A stopped feature still keeps ``last_processed`` so articles are not resent.
    """
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO news_state
            (id, channel_id, guild_id, running, last_processed, server_name, channel_name, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (channel_id, guild_id, running, last_processed, server_name, channel_name))
        conn.commit()
        conn.close()


def load_news_state():
    """Load the news row whether or not the feature is running. None if absent."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT channel_id, guild_id, running, last_processed, server_name, channel_name
            FROM news_state
            WHERE id = 1
        ''')
        row = cursor.fetchone()
        conn.close()

    if row is None:
        return None
    channel_id, guild_id, running, last_processed, server_name, channel_name = row
    return {
        'channel_id': channel_id,
        'guild_id': guild_id,
        'running': bool(running),
        'last_processed': last_processed,
        'server_name': server_name,
        'channel_name': channel_name,
    }


def remove_forex_channel_state(channel_id):
    """Remove a Forex notifier channel from persistence."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM forex_channel_states WHERE channel_id = ?', (channel_id,))
        conn.commit()
        conn.close()


def remove_channel_state(channel_id, interval=None):
    """Remove channel state for a specific interval or all intervals of a channel."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        if interval is not None:
            cursor.execute('DELETE FROM channel_states WHERE channel_id = ? AND interval = ?', (channel_id, interval))
        else:
            cursor.execute('DELETE FROM channel_states WHERE channel_id = ?', (channel_id,))
        conn.commit()
        conn.close()


def save_previous_rankings(rankings_data, session_name, interval=300):
    """Save rankings list [(symbol, rank), ...] into previous_rankings."""
    if not rankings_data:
        return
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            for symbol, rank in rankings_data:
                cursor.execute('''
                    INSERT OR REPLACE INTO previous_rankings 
                    (session_name, symbol, rank, interval, scan_time)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (session_name, symbol, rank, interval))
            conn.commit()
        except Exception as e:
            logger.error(f"Error saving rankings: {e}")
        finally:
            conn.close()


def load_previous_rankings(session_name, interval=300):
    """Load latest rankings for a given session and interval."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT symbol, rank
                FROM previous_rankings
                WHERE session_name = ? AND interval = ?
                ORDER BY scan_time DESC, rank ASC
                LIMIT 30
            ''', (session_name, interval))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error loading rankings: {e}")
            return []
        finally:
            conn.close()
