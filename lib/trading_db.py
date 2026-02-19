"""
SQLite database for trading bot parameter tracking and performance history
"""
import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = 'trading_data.db'

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dicts
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_database():
    """Initialize database schema"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Parameter changes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS parameter_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                bot_name TEXT NOT NULL,
                old_params TEXT,
                new_params TEXT NOT NULL,
                diff TEXT,
                trigger TEXT DEFAULT 'manual',
                notes TEXT
            )
        ''')

        # Performance snapshots table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS performance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                change_id INTEGER NOT NULL,
                snapshot_type TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                fills INTEGER,
                pnl REAL,
                pnl_pct REAL,
                partial_fill_rate REAL,
                avg_fill_size REAL,
                fills_per_hour REAL,
                total_volume REAL,
                total_fees REAL,
                hourly_pnl REAL,
                buy_count INTEGER,
                sell_count INTEGER,
                starting_capital REAL,
                ending_capital REAL,
                alpha REAL,
                raw_data TEXT,
                FOREIGN KEY(change_id) REFERENCES parameter_changes(id)
            )
        ''')

        # Balance snapshots table (captures balances at window boundaries)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                kntq_balance REAL NOT NULL,
                usdh_balance REAL NOT NULL,
                kntq_price REAL NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Static window snapshots table (fixed 8-hour windows)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS static_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                window_start DATETIME NOT NULL,
                window_end DATETIME NOT NULL,
                window_label TEXT NOT NULL,
                fills INTEGER,
                total_pnl REAL,
                total_pnl_pct REAL,
                trading_pnl REAL,
                trading_pnl_pct REAL,
                market_pnl REAL,
                market_pnl_pct REAL,
                total_volume REAL,
                total_fees REAL,
                buy_count INTEGER,
                sell_count INTEGER,
                partial_fill_rate REAL,
                avg_fill_size REAL,
                fills_per_hour REAL,
                start_capital REAL,
                end_capital REAL,
                start_price REAL,
                end_price REAL,
                raw_stats TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create indexes for faster queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_param_changes_bot
            ON parameter_changes(bot_name, timestamp DESC)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_snapshots_change
            ON performance_snapshots(change_id, snapshot_type)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_balance_snapshots_bot
            ON balance_snapshots(bot_name, timestamp DESC)
        ''')

        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_balance_snapshots_unique
            ON balance_snapshots(bot_name, timestamp)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_static_windows_bot
            ON static_windows(bot_name, window_start DESC)
        ''')

        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_static_windows_unique
            ON static_windows(bot_name, window_start, window_end)
        ''')

        # System events / configuration timeline table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                bot_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_title TEXT NOT NULL,
                description TEXT,
                metadata TEXT,
                notes TEXT
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_system_events_bot
            ON system_events(bot_name, timestamp DESC)
        ''')

        print("[DB] Database initialized successfully")

def log_parameter_change(bot_name, old_params, new_params, diff, trigger='manual', notes=None):
    """Log a parameter change"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO parameter_changes
            (bot_name, old_params, new_params, diff, trigger, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            bot_name,
            json.dumps(old_params) if old_params else None,
            json.dumps(new_params),
            json.dumps(diff) if diff else None,
            trigger,
            notes
        ))
        change_id = cursor.lastrowid
        print(f"[DB] Logged parameter change #{change_id} for {bot_name}")
        return change_id

def save_performance_snapshot(change_id, snapshot_type, timeframe, metrics):
    """Save a performance snapshot (before/after a parameter change)"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO performance_snapshots
            (change_id, snapshot_type, timeframe, fills, pnl, pnl_pct,
             partial_fill_rate, avg_fill_size, fills_per_hour, total_volume,
             total_fees, hourly_pnl, buy_count, sell_count, starting_capital,
             ending_capital, alpha, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            change_id,
            snapshot_type,
            timeframe,
            metrics.get('fills'),
            metrics.get('pnl'),
            metrics.get('pnl_pct'),
            metrics.get('partial_fill_rate'),
            metrics.get('avg_fill_size'),
            metrics.get('fills_per_hour'),
            metrics.get('total_volume'),
            metrics.get('total_fees'),
            metrics.get('hourly_pnl'),
            metrics.get('buy_count'),
            metrics.get('sell_count'),
            metrics.get('starting_capital'),
            metrics.get('ending_capital'),
            metrics.get('alpha'),
            json.dumps(metrics) if metrics else None
        ))
        snapshot_id = cursor.lastrowid
        print(f"[DB] Saved {snapshot_type} snapshot #{snapshot_id} for change #{change_id}")
        return snapshot_id

def get_latest_params(bot_name):
    """Get the most recent parameters for a bot"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT new_params
            FROM parameter_changes
            WHERE bot_name = ?
            ORDER BY timestamp DESC
            LIMIT 1
        ''', (bot_name,))

        row = cursor.fetchone()
        if row:
            return json.loads(row['new_params'])
        return None

def get_parameter_history(bot_name, limit=10):
    """Get parameter change history for a bot"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, timestamp, old_params, new_params, diff, trigger, notes
            FROM parameter_changes
            WHERE bot_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (bot_name, limit))

        changes = []
        for row in cursor.fetchall():
            changes.append({
                'id': row['id'],
                'timestamp': row['timestamp'],
                'old_params': json.loads(row['old_params']) if row['old_params'] else None,
                'new_params': json.loads(row['new_params']),
                'diff': json.loads(row['diff']) if row['diff'] else None,
                'trigger': row['trigger'],
                'notes': row['notes']
            })
        return changes

def get_snapshots_for_change(change_id):
    """Get all performance snapshots for a parameter change"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM performance_snapshots
            WHERE change_id = ?
            ORDER BY snapshot_type, timeframe
        ''', (change_id,))

        snapshots = {}
        for row in cursor.fetchall():
            key = f"{row['snapshot_type']}_{row['timeframe']}"
            snapshots[key] = dict(row)
        return snapshots

def calculate_param_diff(old_params, new_params):
    """Calculate the difference between two parameter sets"""
    if not old_params:
        return {'type': 'initial', 'changes': {}}

    diff = {'type': 'update', 'changes': {}}

    # Check all keys in new_params
    for key, new_value in new_params.items():
        old_value = old_params.get(key)
        # Only count as a change if:
        # 1. The parameter existed before (old_value is not None)
        # 2. AND the value actually changed
        # This prevents false positives when we start tracking new parameters
        if old_value is not None and old_value != new_value:
            diff['changes'][key] = {
                'old': old_value,
                'new': new_value
            }

    # Check for removed keys
    for key in old_params:
        if key not in new_params:
            diff['changes'][key] = {
                'old': old_params[key],
                'new': None,
                'removed': True
            }

    return diff

def format_param_change_summary(diff):
    """Format a human-readable summary of parameter changes"""
    if not diff or diff.get('type') == 'initial':
        return "Initial parameters"

    changes = diff.get('changes', {})
    if not changes:
        return "No changes"

    summaries = []
    for key, change in changes.items():
        old_val = change.get('old')
        new_val = change.get('new')

        # Format based on parameter type
        if 'size' in key.lower():
            summaries.append(f"{key}: {old_val} → {new_val} XMR")
        elif 'bps' in key.lower():
            summaries.append(f"{key}: {old_val} → {new_val} bps")
        elif 'position' in key.lower():
            summaries.append(f"{key}: {old_val} → {new_val} XMR")
        elif 'interval' in key.lower():
            summaries.append(f"{key}: {old_val}s → {new_val}s")
        else:
            summaries.append(f"{key}: {old_val} → {new_val}")

    return ", ".join(summaries)

def get_changes_needing_after_snapshots():
    """Get parameter changes that need 'after' snapshots"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Find changes from the last 48 hours that might need after snapshots
        cursor.execute('''
            SELECT id, timestamp
            FROM parameter_changes
            WHERE timestamp >= datetime('now', '-48 hours')
            ORDER BY timestamp DESC
        ''')

        changes_needing_snapshots = []

        for row in cursor.fetchall():
            change_id = row['id']
            change_time = datetime.fromisoformat(row['timestamp'])

            # Check which timeframes need after snapshots
            timeframes_needed = []

            for tf in ['last_1h', 'last_8h', 'last_24h']:
                # Check if after snapshot exists
                cursor.execute('''
                    SELECT id FROM performance_snapshots
                    WHERE change_id = ? AND snapshot_type = 'after' AND timeframe = ?
                ''', (change_id, tf))

                if not cursor.fetchone():
                    # No after snapshot exists - check if enough time has passed
                    now = datetime.now()
                    hours_passed = (now - change_time).total_seconds() / 3600

                    # Wait at least the timeframe duration before taking "after" snapshot
                    if tf == 'last_1h' and hours_passed >= 1.1:
                        timeframes_needed.append(tf)
                    elif tf == 'last_8h' and hours_passed >= 8.1:
                        timeframes_needed.append(tf)
                    elif tf == 'last_24h' and hours_passed >= 24.1:
                        timeframes_needed.append(tf)

            if timeframes_needed:
                changes_needing_snapshots.append({
                    'change_id': change_id,
                    'timeframes': timeframes_needed
                })

        return changes_needing_snapshots

def save_static_window(bot_name, window_start, window_end, window_label, stats):
    """Save a completed static window snapshot

    Args:
        bot_name: Name of the bot (e.g., 'kntq', 'xmr1')
        window_start: datetime object for window start
        window_end: datetime object for window end
        window_label: Label like "Day 0: 00:00-08:00"
        stats: Dictionary of statistics for the window
    """
    def json_serializer(obj):
        """Custom JSON serializer for datetime objects"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    with get_db() as conn:
        cursor = conn.cursor()

        # Use INSERT OR REPLACE to handle duplicate windows
        cursor.execute('''
            INSERT OR REPLACE INTO static_windows (
                bot_name, window_start, window_end, window_label,
                fills, total_pnl, total_pnl_pct, trading_pnl, trading_pnl_pct,
                market_pnl, market_pnl_pct, total_volume, total_fees,
                buy_count, sell_count, partial_fill_rate, avg_fill_size,
                fills_per_hour, start_capital, end_capital, start_price,
                end_price, raw_stats
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            bot_name,
            window_start.isoformat(),
            window_end.isoformat(),
            window_label,
            stats.get('trade_count', 0),
            stats.get('total_pnl', 0),
            stats.get('pnl_pct', 0),
            stats.get('trading_pnl', 0),
            stats.get('trading_pnl_pct', 0),
            stats.get('market_pnl', 0),
            stats.get('market_pnl_pct', 0),
            stats.get('total_volume', 0),
            stats.get('total_fees', 0),
            stats.get('buy_count', 0),
            stats.get('sell_count', 0),
            stats.get('partial_rate', 0),
            stats.get('avg_fill_size', 0),
            stats.get('fills_per_hour', 0),
            stats.get('start_capital', 0),
            stats.get('end_capital', 0),
            stats.get('start_price', 0),
            stats.get('end_price', 0),
            json.dumps(stats, default=json_serializer)
        ))

        return cursor.lastrowid

def get_static_windows(bot_name, limit=100, offset=0):
    """Get static window snapshots for a bot

    Args:
        bot_name: Name of the bot
        limit: Maximum number of windows to return
        offset: Number of windows to skip (for pagination)

    Returns:
        List of window dictionaries, sorted by window_start DESC
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM static_windows
            WHERE bot_name = ?
            ORDER BY window_start DESC
            LIMIT ? OFFSET ?
        ''', (bot_name, limit, offset))

        rows = cursor.fetchall()
        windows = []
        for row in rows:
            window = dict(row)
            # Parse raw_stats JSON
            if window.get('raw_stats'):
                window['raw_stats'] = json.loads(window['raw_stats'])
            windows.append(window)

        return windows

def get_static_window_summary(bot_name, days=30):
    """Get summary statistics for static windows

    Args:
        bot_name: Name of the bot
        days: Number of days to include in summary

    Returns:
        Dictionary with summary stats
    """
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                COUNT(*) as window_count,
                SUM(fills) as total_fills,
                AVG(total_pnl) as avg_pnl,
                SUM(total_pnl) as total_pnl,
                AVG(trading_pnl) as avg_trading_pnl,
                SUM(trading_pnl) as total_trading_pnl,
                AVG(market_pnl) as avg_market_pnl,
                SUM(market_pnl) as total_market_pnl,
                SUM(CASE WHEN total_pnl > 0 THEN 1 ELSE 0 END) as profitable_windows,
                SUM(CASE WHEN trading_pnl > 0 THEN 1 ELSE 0 END) as trading_positive_windows
            FROM static_windows
            WHERE bot_name = ? AND window_start >= ?
        ''', (bot_name, cutoff.isoformat()))

        row = cursor.fetchone()
        if not row:
            return None

        result = dict(row)

        # Calculate win rates
        if result['window_count'] > 0:
            result['profitable_window_pct'] = (result['profitable_windows'] / result['window_count']) * 100
            result['trading_positive_pct'] = (result['trading_positive_windows'] / result['window_count']) * 100
        else:
            result['profitable_window_pct'] = 0
            result['trading_positive_pct'] = 0

        return result

def save_balance_snapshot(bot_name, timestamp, kntq_balance, usdh_balance, kntq_price):
    """Save a balance snapshot at a window boundary

    Args:
        bot_name: Name of the bot (e.g., 'kntq', 'xmr1')
        timestamp: datetime object for the snapshot time
        kntq_balance: KNTQ balance at this time
        usdh_balance: USDH balance at this time
        kntq_price: KNTQ price at this time
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Use INSERT OR REPLACE to handle duplicate snapshots
        cursor.execute('''
            INSERT OR REPLACE INTO balance_snapshots (
                bot_name, timestamp, kntq_balance, usdh_balance, kntq_price
            ) VALUES (?, ?, ?, ?, ?)
        ''', (
            bot_name,
            timestamp.isoformat(),
            kntq_balance,
            usdh_balance,
            kntq_price
        ))

        return cursor.lastrowid

def get_balance_snapshot(bot_name, target_time, tolerance_minutes=10):
    """Get balance snapshot near a target time

    Args:
        bot_name: Name of the bot
        target_time: datetime object for the target time
        tolerance_minutes: How many minutes +/- to search for a snapshot

    Returns:
        dict with snapshot data, or None if not found
    """
    from datetime import timedelta

    start_time = target_time - timedelta(minutes=tolerance_minutes)
    end_time = target_time + timedelta(minutes=tolerance_minutes)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM balance_snapshots
            WHERE bot_name = ?
            AND timestamp >= ?
            AND timestamp <= ?
            ORDER BY ABS(julianday(timestamp) - julianday(?)) ASC
            LIMIT 1
        ''', (bot_name, start_time.isoformat(), end_time.isoformat(), target_time.isoformat()))

        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

def get_recent_balance_snapshots(bot_name, limit=50):
    """Get recent balance snapshots

    Args:
        bot_name: Name of the bot
        limit: Maximum number of snapshots to return

    Returns:
        List of snapshot dictionaries
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM balance_snapshots
            WHERE bot_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (bot_name, limit))

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def log_system_event(bot_name, event_type, event_title, description=None, metadata=None, notes=None, timestamp=None):
    """Log a system event / configuration change

    Args:
        bot_name: Name of the bot (e.g., 'kntq', 'xmr1', 'all')
        event_type: Type of event (e.g., 'architecture', 'deployment', 'configuration', 'optimization')
        event_title: Short title for the event (e.g., "WebSocket Integration")
        description: Longer description of what changed
        metadata: Dictionary of additional metadata
        notes: Additional notes
        timestamp: Optional custom timestamp (default: current time)

    Returns:
        Event ID
    """
    with get_db() as conn:
        cursor = conn.cursor()

        if timestamp:
            cursor.execute('''
                INSERT INTO system_events
                (timestamp, bot_name, event_type, event_title, description, metadata, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp,
                bot_name,
                event_type,
                event_title,
                description,
                json.dumps(metadata) if metadata else None,
                notes
            ))
        else:
            cursor.execute('''
                INSERT INTO system_events
                (bot_name, event_type, event_title, description, metadata, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                bot_name,
                event_type,
                event_title,
                description,
                json.dumps(metadata) if metadata else None,
                notes
            ))

        event_id = cursor.lastrowid
        print(f"[DB] Logged system event #{event_id} for {bot_name}: {event_title}")
        return event_id

def get_system_events(bot_name=None, limit=50, event_type=None):
    """Get system events timeline

    Args:
        bot_name: Filter by bot name (None = all bots)
        limit: Maximum number of events to return
        event_type: Filter by event type (None = all types)

    Returns:
        List of event dictionaries, sorted by timestamp DESC
    """
    with get_db() as conn:
        cursor = conn.cursor()

        query = 'SELECT * FROM system_events WHERE 1=1'
        params = []

        if bot_name:
            query += ' AND (bot_name = ? OR bot_name = "all")'
            params.append(bot_name)

        if event_type:
            query += ' AND event_type = ?'
            params.append(event_type)

        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)

        cursor.execute(query, params)

        events = []
        for row in cursor.fetchall():
            event = dict(row)
            # Parse metadata JSON if present
            if event.get('metadata'):
                event['metadata'] = json.loads(event['metadata'])
            events.append(event)

        return events

def get_event_types():
    """Get all distinct event types in the system"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT event_type FROM system_events ORDER BY event_type')
        return [row['event_type'] for row in cursor.fetchall()]

# Initialize database on import
# init_database()  # Commented out - using new schema from migrations instead
