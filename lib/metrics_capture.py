"""
Metrics Capture Module
Handles 1-minute boundary snapshots for time-series analytics
"""

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Dict, Any, Optional, Callable

DATABASE_PATH = "trading_data.db"

class MetricsCapture:
    """Captures metrics every minute at boundary"""

    def __init__(self, pair: str, get_state_callback: Callable):
        """
        Initialize metrics capture

        Args:
            pair: Trading pair (e.g., 'KNTQ/USDH')
            get_state_callback: Function that returns current bot state dict
        """
        self.pair = pair
        self.get_state_callback = get_state_callback
        self.worker_thread = None
        self.running = False
        self.last_snapshot = None

        # Cumulative counters (reset on bot restart or midnight)
        self.cumulative_fills = 0
        self.cumulative_volume = 0
        self.cumulative_realized_pnl = 0
        self.cumulative_fees = 0

    def start(self):
        """Start the metrics capture worker thread"""
        if self.running:
            print("⚠️  Metrics capture already running")
            return

        self.running = True
        self.worker_thread = Thread(target=self._snapshot_worker, daemon=True)
        self.worker_thread.start()
        print(f"✓ Metrics capture started for {self.pair}")

    def stop(self):
        """Stop the metrics capture worker"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        print(f"✓ Metrics capture stopped for {self.pair}")

    def _snapshot_worker(self):
        """Worker thread that captures metrics every minute"""
        print(f"   Metrics worker running for {self.pair}")

        while self.running:
            try:
                # Calculate next minute boundary
                now = datetime.now(timezone.utc)
                next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)

                # Sleep until boundary
                sleep_seconds = (next_minute - now).total_seconds()
                print(f"   [METRICS DEBUG] Sleeping {sleep_seconds:.1f}s until {next_minute.strftime('%H:%M:%S')}")
                time.sleep(sleep_seconds)

                # Capture snapshot (now guaranteed to be on :00 boundary)
                if self.running:  # Check again in case stopped during sleep
                    print(f"   [METRICS DEBUG] Attempting capture at {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
                    self.capture_snapshot()

            except Exception as e:
                print(f"   ⚠️  Error in metrics worker: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(60)  # Wait a minute before retrying

    def capture_snapshot(self):
        """Capture a 1-minute snapshot at the current boundary"""
        try:
            timestamp = datetime.now(timezone.utc).replace(second=0, microsecond=0)

            # Get current bot state from callback
            state = self.get_state_callback()

            # Check if we have essential market data (API might be down)
            if not state.get('mid_price'):
                print(f"   ⚠️  Skipping metrics capture - no market data available (API down?)")
                return

            # Get fills since last snapshot
            fills_data = self._get_fills_since_last_snapshot(timestamp)

            # Update cumulatives
            self.cumulative_fills += fills_data['fills_count']
            self.cumulative_volume += fills_data['volume_quote']
            self.cumulative_realized_pnl += fills_data['realized_pnl']
            self.cumulative_fees += fills_data['fees_paid']

            # Calculate price change
            price_change_bps = 0
            if self.last_snapshot and self.last_snapshot.get('mid_price') and state.get('mid_price'):
                price_change_bps = (
                    (state['mid_price'] - self.last_snapshot['mid_price'])
                    / self.last_snapshot['mid_price'] * 10000
                )

            # Build metrics record
            metrics = {
                'timestamp': timestamp,
                'pair': self.pair,
                'parameter_set_id': state.get('parameter_set_id'),

                # Balances
                'base_balance': state.get('base_balance'),
                'quote_balance': state.get('quote_balance'),
                'base_total': state.get('base_total'),
                'quote_total': state.get('quote_total'),

                # Prices
                'mid_price': state.get('mid_price'),
                'bid_price': state.get('bid_price'),
                'ask_price': state.get('ask_price'),
                'spread_bps': state.get('spread_bps'),

                # Total value
                'total_value_usd': state.get('total_value_usd'),

                # Activity during previous minute
                'fills_count': fills_data['fills_count'],
                'buy_fills': fills_data['buy_fills'],
                'sell_fills': fills_data['sell_fills'],
                'volume_base': fills_data['volume_base'],
                'volume_quote': fills_data['volume_quote'],

                # PnL
                'realized_pnl': fills_data['realized_pnl'],
                'fees_paid': fills_data['fees_paid'],
                'net_realized_pnl': fills_data['realized_pnl'] - fills_data['fees_paid'],

                # Price movement
                'price_change_bps': price_change_bps,

                # Cumulatives
                'cumulative_fills': self.cumulative_fills,
                'cumulative_volume_quote': self.cumulative_volume,
                'cumulative_realized_pnl': self.cumulative_realized_pnl,
                'cumulative_fees': self.cumulative_fees,
                'cumulative_net_pnl': self.cumulative_realized_pnl - self.cumulative_fees,

                # Bot state
                'bot_running': state.get('bot_running', True),
                'bid_live': state.get('bid_live', False),
                'ask_live': state.get('ask_live', False),
                'our_bid_price': state.get('our_bid_price'),
                'our_ask_price': state.get('our_ask_price'),
                'our_bid_size': state.get('our_bid_size'),
                'our_ask_size': state.get('our_ask_size'),

                # Spread capture
                'avg_spread_captured_bps': fills_data.get('avg_spread_captured_bps'),
            }

            # Insert to database
            self._insert_metrics(metrics)

            # Update last snapshot
            self.last_snapshot = metrics

            # Log summary
            if fills_data['fills_count'] > 0:
                print(f"   📊 Metrics captured: {fills_data['fills_count']} fills, "
                      f"${fills_data['volume_quote']:.2f} volume, "
                      f"${fills_data['realized_pnl']:.2f} PnL")

        except Exception as e:
            print(f"   ⚠️  Error capturing metrics: {e}")
            import traceback
            traceback.print_exc()

    def _get_fills_since_last_snapshot(self, current_timestamp: datetime) -> Dict[str, Any]:
        """Get fills that occurred since last snapshot"""
        if not self.last_snapshot:
            # First snapshot - get fills from last minute
            start_time = current_timestamp - timedelta(minutes=1)
        else:
            start_time = self.last_snapshot['timestamp']

        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Query fills in time range
            cursor.execute("""
                SELECT
                    COUNT(*) as fills_count,
                    SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buy_fills,
                    SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sell_fills,
                    COALESCE(SUM(base_amount), 0) as volume_base,
                    COALESCE(SUM(quote_amount), 0) as volume_quote,
                    COALESCE(SUM(realized_pnl), 0) as realized_pnl,
                    COALESCE(SUM(fee), 0) as fees_paid,
                    AVG(spread_bps) as avg_spread_captured_bps
                FROM fills
                WHERE pair = ?
                  AND timestamp > ?
                  AND timestamp <= ?
            """, (self.pair, start_time, current_timestamp))

            row = cursor.fetchone()

            return {
                'fills_count': row[0] or 0,
                'buy_fills': row[1] or 0,
                'sell_fills': row[2] or 0,
                'volume_base': float(row[3] or 0),
                'volume_quote': float(row[4] or 0),
                'realized_pnl': float(row[5] or 0),
                'fees_paid': float(row[6] or 0),
                'avg_spread_captured_bps': float(row[7]) if row[7] else None
            }

        finally:
            cursor.close()
            conn.close()

    def _insert_metrics(self, metrics: Dict[str, Any]):
        """Insert metrics record to database"""
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO metrics_1min (
                    timestamp, pair, parameter_set_id,
                    base_balance, quote_balance, base_total, quote_total,
                    mid_price, bid_price, ask_price, spread_bps, total_value_usd,
                    fills_count, buy_fills, sell_fills, volume_base, volume_quote,
                    realized_pnl, fees_paid, net_realized_pnl,
                    price_change_bps,
                    cumulative_fills, cumulative_volume_quote,
                    cumulative_realized_pnl, cumulative_fees, cumulative_net_pnl,
                    bot_running, bid_live, ask_live,
                    our_bid_price, our_ask_price, our_bid_size, our_ask_size,
                    avg_spread_captured_bps
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?
                )
                ON CONFLICT (timestamp, pair) DO UPDATE SET
                    parameter_set_id = EXCLUDED.parameter_set_id,
                    base_balance = EXCLUDED.base_balance,
                    quote_balance = EXCLUDED.quote_balance,
                    base_total = EXCLUDED.base_total,
                    quote_total = EXCLUDED.quote_total,
                    mid_price = EXCLUDED.mid_price,
                    total_value_usd = EXCLUDED.total_value_usd,
                    fills_count = EXCLUDED.fills_count,
                    realized_pnl = EXCLUDED.realized_pnl,
                    fees_paid = EXCLUDED.fees_paid,
                    net_realized_pnl = EXCLUDED.net_realized_pnl,
                    cumulative_fills = EXCLUDED.cumulative_fills,
                    cumulative_realized_pnl = EXCLUDED.cumulative_realized_pnl,
                    bot_running = EXCLUDED.bot_running,
                    bid_live = EXCLUDED.bid_live,
                    ask_live = EXCLUDED.ask_live
            """, (
                metrics['timestamp'], metrics['pair'], metrics['parameter_set_id'],
                metrics['base_balance'], metrics['quote_balance'],
                metrics['base_total'], metrics['quote_total'],
                metrics['mid_price'], metrics['bid_price'], metrics['ask_price'],
                metrics['spread_bps'], metrics['total_value_usd'],
                metrics['fills_count'], metrics['buy_fills'], metrics['sell_fills'],
                metrics['volume_base'], metrics['volume_quote'],
                metrics['realized_pnl'], metrics['fees_paid'], metrics['net_realized_pnl'],
                metrics['price_change_bps'],
                metrics['cumulative_fills'], metrics['cumulative_volume_quote'],
                metrics['cumulative_realized_pnl'], metrics['cumulative_fees'],
                metrics['cumulative_net_pnl'],
                metrics['bot_running'], metrics['bid_live'], metrics['ask_live'],
                metrics['our_bid_price'], metrics['our_ask_price'],
                metrics['our_bid_size'], metrics['our_ask_size'],
                metrics['avg_spread_captured_bps']
            ))

            conn.commit()

        finally:
            cursor.close()
            conn.close()

    def reset_cumulatives(self):
        """Reset cumulative counters (call at midnight or bot restart)"""
        self.cumulative_fills = 0
        self.cumulative_volume = 0
        self.cumulative_realized_pnl = 0
        self.cumulative_fees = 0
        print(f"   Cumulative metrics reset for {self.pair}")
