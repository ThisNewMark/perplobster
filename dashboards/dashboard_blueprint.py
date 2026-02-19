#!/usr/bin/env python3
"""
Generic Market Making Dashboard V2 - Blueprint Version
Can be used for any trading pair

Usage: Import create_dashboard_blueprint() and register with Flask app
"""

from flask import Blueprint, render_template_string, jsonify, request
from datetime import datetime, timedelta, timezone
import sqlite3
import json

import os

# Default database path (can be overridden when creating blueprint)
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trading_data.db")

def create_dashboard_blueprint(pair_name, route_prefix, database_path=None):
    """
    Create a dashboard blueprint for a specific trading pair

    Args:
        pair_name: Trading pair like "XMR1/USDC", "KNTQ/USDH", "PURR/USDC"
        route_prefix: URL prefix like "xmr1", "kntq", "purr"
        database_path: Optional path to database (defaults to vibetraders/trading_data.db)

    Returns:
        Flask Blueprint
    """
    bp = Blueprint(f'dashboard_{route_prefix}', __name__, url_prefix=f'/{route_prefix}')

    # This pair's name (used in all database queries)
    PAIR = pair_name
    DB_PATH = database_path or DATABASE_PATH

    def get_db():
        """Get database connection"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    def calculate_toxicity_metrics(start_time_str, end_time_str=None):
        """Calculate toxicity/adverse selection metrics for a time window"""
        conn = get_db()
        cursor = conn.cursor()
        # Get fills for the time window
        if end_time_str:
            cursor.execute("""
                SELECT timestamp, price, side, base_amount
                FROM fills
                WHERE pair = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
            """, (PAIR, start_time_str, end_time_str))
        else:
            cursor.execute("""
                SELECT timestamp, price, side, base_amount
                FROM fills
                WHERE pair = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (PAIR, start_time_str))
        fills = cursor.fetchall()
        conn.close()
        if len(fills) < 10:
            return {
                'insufficient_data': True,
                'message': 'Need at least 10 fills for toxicity analysis',
                'avg_markout_5s': 0,
                'avg_markout_30s': 0,
                'pct_negative_30s': 0,
                'imbalance_score': 0,
                'buy_pct': 50,
                'sell_pct': 50
            }
        # Convert to list of dicts for easier processing
        trades = []
        for fill in fills:
            from datetime import datetime
            trades.append({
                'time': datetime.fromisoformat(fill['timestamp'].replace('+00:00', '')),
                'price': float(fill['price']),
                'side': fill['side'],
                'size': float(fill['base_amount'])
            })
        # 1. MARKOUT ANALYSIS (approximate using subsequent fill prices)
        markouts_5s = []
        markouts_30s = []
        negative_30s_count = 0
        for i, trade in enumerate(trades):
            fill_price = trade['price']
            fill_time = trade['time']
            side = trade['side']
            # Find fills within 5s and 30s windows
            future_prices_5s = []
            future_prices_30s = []
            for j in range(i+1, len(trades)):
                time_diff = (trades[j]['time'] - fill_time).total_seconds()
                if time_diff <= 5:
                    future_prices_5s.append(trades[j]['price'])
                if time_diff <= 30:
                    future_prices_30s.append(trades[j]['price'])
                if time_diff > 30:
                    break
            # Calculate markout (positive = good for you, negative = toxic)
            if future_prices_5s:
                mid_5s = sum(future_prices_5s) / len(future_prices_5s)
                if side == 'buy':
                    markout = mid_5s - fill_price  # Want price to go UP after buying
                else:
                    markout = fill_price - mid_5s  # Want price to go DOWN after selling
                markouts_5s.append((markout / fill_price) * 10000)  # Convert to bps
            if future_prices_30s:
                mid_30s = sum(future_prices_30s) / len(future_prices_30s)
                if side == 'buy':
                    markout = mid_30s - fill_price
                else:
                    markout = fill_price - mid_30s
                markout_bps = (markout / fill_price) * 10000
                markouts_30s.append(markout_bps)
                if markout_bps < 0:
                    negative_30s_count += 1
        # 2. FILL SIDE IMBALANCE
        buys = [t for t in trades if t['side'] == 'buy']
        sells = [t for t in trades if t['side'] == 'sell']
        buy_pct = len(buys) / len(trades) * 100 if trades else 50
        sell_pct = len(sells) / len(trades) * 100 if trades else 50
        imbalance_score = abs(buy_pct - 50) * 2  # 0-100 scale
        # Calculate averages
        avg_markout_5s = sum(markouts_5s) / len(markouts_5s) if markouts_5s else 0
        avg_markout_30s = sum(markouts_30s) / len(markouts_30s) if markouts_30s else 0
        pct_negative_30s = (negative_30s_count / len(markouts_30s) * 100) if markouts_30s else 0
        return {
            'insufficient_data': False,
            'avg_markout_5s': avg_markout_5s,
            'avg_markout_30s': avg_markout_30s,
            'pct_negative_30s': pct_negative_30s,
            'imbalance_score': imbalance_score,
            'buy_pct': buy_pct,
            'sell_pct': sell_pct,
            'markout_samples': len(markouts_30s)
        }
    def get_current_status():
        """Get latest bot status from most recent metric"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                timestamp,
                base_balance,
                quote_balance,
                base_total,
                quote_total,
                mid_price,
                total_value_usd,
                bid_live,
                ask_live,
                our_bid_price,
                our_ask_price,
                parameter_set_id
            FROM metrics_1min
            WHERE pair = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (PAIR,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            'timestamp': row['timestamp'],
            'base_balance': row['base_balance'],
            'quote_balance': row['quote_balance'],
            'base_total': row['base_total'],
            'quote_total': row['quote_total'],
            'mid_price': row['mid_price'],
            'total_value_usd': row['total_value_usd'],
            'bid_live': bool(row['bid_live']),
            'ask_live': bool(row['ask_live']),
            'our_bid_price': row['our_bid_price'],
            'our_ask_price': row['our_ask_price'],
            'parameter_set_id': row['parameter_set_id']
        }
    def get_window_stats(start_time_str, end_time_str=None):
        """Get statistics for a time window with inventory tracking"""
        conn = get_db()
        cursor = conn.cursor()
        print(f"   [WINDOW DEBUG] Looking for data >= {start_time_str}")
        # Get start snapshot - find first metric at or after start time
        cursor.execute("""
            SELECT base_total, quote_total, mid_price, total_value_usd, timestamp
            FROM metrics_1min
            WHERE pair = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT 1
        """, (PAIR, start_time_str))
        start_row = cursor.fetchone()
        if not start_row:
            print(f"   [WINDOW DEBUG] No start row found for {start_time_str}")
            conn.close()
            return None
        # Use actual start timestamp for aggregations
        actual_start = start_row['timestamp']
        print(f"   [WINDOW DEBUG] Found start row at {actual_start}")
        # Get end snapshot (or current if no end time specified)
        if end_time_str:
            cursor.execute("""
                SELECT base_total, quote_total, mid_price, total_value_usd
                FROM metrics_1min
                WHERE pair = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (PAIR, actual_start, end_time_str))
        else:
            cursor.execute("""
                SELECT base_total, quote_total, mid_price, total_value_usd
                FROM metrics_1min
                WHERE pair = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (PAIR, actual_start))
        end_row = cursor.fetchone()
        if not end_row:
            conn.close()
            return None
        # Get aggregates for the window
        if end_time_str:
            cursor.execute("""
                SELECT
                    COUNT(*) as minutes,
                    SUM(fills_count) as fills,
                    SUM(buy_fills) as buy_fills,
                    SUM(sell_fills) as sell_fills,
                    SUM(volume_quote) as volume,
                    SUM(realized_pnl) as realized_pnl,
                    SUM(fees_paid) as fees,
                    SUM(net_realized_pnl) as net_pnl,
                    AVG(mid_price) as avg_price,
                    MIN(mid_price) as low_price,
                    MAX(mid_price) as high_price,
                    SUM(CASE WHEN bid_live AND ask_live THEN 1 ELSE 0 END) as both_live_minutes
                FROM metrics_1min
                WHERE pair = ? AND timestamp >= ? AND timestamp < ?
            """, (PAIR, actual_start, end_time_str))
        else:
            cursor.execute("""
                SELECT
                    COUNT(*) as minutes,
                    SUM(fills_count) as fills,
                    SUM(buy_fills) as buy_fills,
                    SUM(sell_fills) as sell_fills,
                    SUM(volume_quote) as volume,
                    SUM(realized_pnl) as realized_pnl,
                    SUM(fees_paid) as fees,
                    SUM(net_realized_pnl) as net_pnl,
                    AVG(mid_price) as avg_price,
                    MIN(mid_price) as low_price,
                    MAX(mid_price) as high_price,
                    SUM(CASE WHEN bid_live AND ask_live THEN 1 ELSE 0 END) as both_live_minutes
                FROM metrics_1min
                WHERE pair = ? AND timestamp >= ?
            """, (PAIR, actual_start))
        agg_row = cursor.fetchone()
        # Get fills data directly from fills table for this window
        if end_time_str:
            cursor.execute("""
                SELECT
                    COUNT(*) as fills_count,
                    SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buy_fills,
                    SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sell_fills,
                    COALESCE(SUM(quote_amount), 0) as volume_quote,
                    COALESCE(SUM(fee), 0) as fees_paid
                FROM fills
                WHERE pair = ? AND timestamp >= ? AND timestamp < ?
            """, (PAIR, actual_start, end_time_str))
        else:
            cursor.execute("""
                SELECT
                    COUNT(*) as fills_count,
                    SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buy_fills,
                    SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sell_fills,
                    COALESCE(SUM(quote_amount), 0) as volume_quote,
                    COALESCE(SUM(fee), 0) as fees_paid
                FROM fills
                WHERE pair = ? AND timestamp >= ?
            """, (PAIR, actual_start))
        fills_row = cursor.fetchone()
        conn.close()
        if not agg_row or agg_row['minutes'] == 0:
            return None
        # Calculate inventory changes and PnL breakdown
        start_base = float(start_row['base_total'] or 0)
        start_quote = float(start_row['quote_total'] or 0)
        start_price = float(start_row['mid_price'] or 0)
        start_value = float(start_row['total_value_usd'] or 0)
        end_base = float(end_row['base_total'] or 0)
        end_quote = float(end_row['quote_total'] or 0)
        end_price = float(end_row['mid_price'] or 0)
        end_value = float(end_row['total_value_usd'] or 0)
        # Calculate PnL breakdown (matching old dashboard logic)
        # Start value at start price
        start_total_value = start_base * start_price + start_quote
        # End value at start price (shows trading-only impact)
        end_value_at_start_price = end_base * start_price + end_quote
        # End value at end price (actual current value)
        end_total_value = end_base * end_price + end_quote
        # TRADING PnL: Value change from trading (inventory changes at constant price)
        # This is the profit from buying low and selling high at the spread
        trading_pnl = end_value_at_start_price - start_total_value
        # MARKET PnL: Value change from price movement on remaining inventory
        # This is the unrealized gain/loss from holding inventory as price changed
        market_pnl = end_total_value - end_value_at_start_price
        # TOTAL PnL: Total portfolio value change
        total_pnl = end_total_value - start_total_value
        # Sanity check: trading_pnl + market_pnl should equal total_pnl
        # total_pnl = trading_pnl + market_pnl
        # Inventory delta
        base_delta = end_base - start_base
        quote_delta = end_quote - start_quote
        uptime_pct = (agg_row['both_live_minutes'] / agg_row['minutes'] * 100) if agg_row['minutes'] > 0 else 0
        hours = agg_row['minutes'] / 60.0
        # Use fills data from fills table
        fills_count = fills_row['fills_count'] or 0
        buy_fills = fills_row['buy_fills'] or 0
        sell_fills = fills_row['sell_fills'] or 0
        volume_quote = float(fills_row['volume_quote'] or 0)
        fees_paid = float(fills_row['fees_paid'] or 0)
        pnl_per_hour = trading_pnl / hours if hours > 0 else 0
        # Calculate toxicity metrics for this window
        toxicity = calculate_toxicity_metrics(actual_start, end_time_str)
        return {
            'minutes': agg_row['minutes'],
            'hours': hours,
            'fills': fills_count,
            'buy_fills': buy_fills,
            'sell_fills': sell_fills,
            'volume': volume_quote,
            'realized_pnl': trading_pnl,  # Trading PnL (profit from spreads)
            'unrealized_pnl': market_pnl,  # Market PnL (price movement on inventory)
            'total_pnl': total_pnl,  # Total portfolio change
            'fees': fees_paid,
            'pnl_per_hour': pnl_per_hour,
            'avg_price': float(agg_row['avg_price'] or 0),
            'low_price': float(agg_row['low_price'] or 0),
            'high_price': float(agg_row['high_price'] or 0),
            'uptime_pct': uptime_pct,
            # Inventory tracking
            'start_base': start_base,
            'start_quote': start_quote,
            'start_price': start_price,
            'start_value': start_total_value,
            'end_base': end_base,
            'end_quote': end_quote,
            'end_price': end_price,
            'end_value': end_total_value,
            'base_delta': base_delta,
            'quote_delta': quote_delta,
            # Toxicity metrics
            'toxicity': toxicity,
            # Legacy names for compatibility
            'total_change': total_pnl,
            'price_impact': market_pnl
        }
    def get_parameter_comparison():
        """Compare performance across different parameter sets"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                ps.id,
                ps.base_spread_bps,
                ps.base_order_size,
                ps.inventory_skew_bps_per_unit,
                ps.description,
                ps.created_at,
                ps.update_interval_seconds,
                ps.target_position,
                ps.max_position_size,
                ps.update_threshold_bps,
                COUNT(m.id) as minutes_run,
                SUM(m.fills_count) as total_fills,
                SUM(m.volume_quote) as total_volume,
                SUM(m.realized_pnl) as total_realized_pnl,
                SUM(m.fees_paid) as total_fees,
                SUM(m.net_realized_pnl) as total_net_pnl
            FROM parameter_sets ps
            LEFT JOIN metrics_1min m ON m.parameter_set_id = ps.id
            WHERE ps.pair = ?
            GROUP BY ps.id
            ORDER BY ps.created_at DESC
        """, (PAIR,))
        rows = cursor.fetchall()
        conn.close()
        results = []
        for row in rows:
            hours = row['minutes_run'] / 60.0 if row['minutes_run'] else 0
            pnl_per_hour = row['total_net_pnl'] / hours if hours > 0 else 0
            results.append({
                'id': row['id'],
                'spread_bps': row['base_spread_bps'],
                'order_size': row['base_order_size'],
                'skew': row['inventory_skew_bps_per_unit'],
                'update_interval': row['update_interval_seconds'],
                'target_position': row['target_position'],
                'max_position': row['max_position_size'],
                'quote_refresh_bps': row['update_threshold_bps'],
                'description': row['description'],
                'created_at': row['created_at'],
                'minutes': row['minutes_run'] or 0,
                'hours': hours,
                'fills': row['total_fills'] or 0,
                'volume': row['total_volume'] or 0,
                'net_pnl': row['total_net_pnl'] or 0,
                'pnl_per_hour': pnl_per_hour
            })
        return results
    def get_drawdown():
        """Calculate current drawdown from peak portfolio value"""
        conn = get_db()
        cursor = conn.cursor()
        # Get peak total value
        cursor.execute("""
            SELECT MAX(total_value_usd) as peak_value
            FROM metrics_1min
            WHERE pair = ? AND total_value_usd IS NOT NULL
        """, (PAIR,))
        peak_row = cursor.fetchone()
        peak_value = peak_row['peak_value'] if peak_row else None
        # Get current value
        cursor.execute("""
            SELECT total_value_usd
            FROM metrics_1min
            WHERE pair = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (PAIR,))
        current_row = cursor.fetchone()
        current_value = current_row['total_value_usd'] if current_row else None
        conn.close()
        if peak_value and current_value:
            drawdown_pct = ((current_value - peak_value) / peak_value) * 100
            drawdown_dollars = current_value - peak_value
            return {
                'peak_value': peak_value,
                'current_value': current_value,
                'drawdown_pct': drawdown_pct,
                'drawdown_dollars': drawdown_dollars
            }
        return None
    def get_position_price_data(start_time_str, end_time_str=None):
        """Get position and price data for charting"""
        conn = get_db()
        cursor = conn.cursor()
        if end_time_str:
            cursor.execute("""
                SELECT timestamp, mid_price, base_total
                FROM metrics_1min
                WHERE pair = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
            """, (PAIR, start_time_str, end_time_str))
        else:
            cursor.execute("""
                SELECT timestamp, mid_price, base_total
                FROM metrics_1min
                WHERE pair = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (PAIR, start_time_str))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return None
        # Extract data for charting
        timestamps = []
        prices = []
        positions = []
        for row in rows:
            timestamps.append(row['timestamp'])
            prices.append(float(row['mid_price']) if row['mid_price'] else None)
            positions.append(float(row['base_total']) if row['base_total'] else None)
        # Calculate correlation between price changes and position changes
        correlation = calculate_correlation(prices, positions)
        # Generate insights
        insights = generate_position_insights(timestamps, prices, positions, correlation)
        return {
            'timestamps': timestamps,
            'prices': prices,
            'positions': positions,
            'correlation': correlation,
            'insights': insights
        }
    def calculate_correlation(prices, positions):
        """Calculate Pearson correlation between price and position"""
        if len(prices) < 2 or len(positions) < 2:
            return 0.0
        # Remove None values
        valid_pairs = [(p, pos) for p, pos in zip(prices, positions) if p is not None and pos is not None]
        if len(valid_pairs) < 2:
            return 0.0
        prices_clean = [p for p, _ in valid_pairs]
        positions_clean = [pos for _, pos in valid_pairs]
        # Calculate means
        price_mean = sum(prices_clean) / len(prices_clean)
        pos_mean = sum(positions_clean) / len(positions_clean)
        # Calculate correlation
        numerator = sum((p - price_mean) * (pos - pos_mean) for p, pos in zip(prices_clean, positions_clean))
        price_std = sum((p - price_mean) ** 2 for p in prices_clean) ** 0.5
        pos_std = sum((pos - pos_mean) ** 2 for pos in positions_clean) ** 0.5
        if price_std == 0 or pos_std == 0:
            return 0.0
        correlation = numerator / (price_std * pos_std)
        return correlation
    def generate_position_insights(timestamps, prices, positions, correlation):
        """Generate insights about position and price relationship"""
        insights = []
        # Correlation insight
        if correlation > 0.5:
            insights.append(f"💚 Strong positive correlation (+{correlation:.2f}) - accumulating during price increases")
        elif correlation > 0.2:
            insights.append(f"💡 Slight positive correlation (+{correlation:.2f}) - decent inventory timing")
        elif correlation > -0.2:
            insights.append(f"⚪ Low correlation ({correlation:+.2f}) - inventory changes independent of price")
        elif correlation > -0.5:
            insights.append(f"⚠️  Negative correlation ({correlation:+.2f}) - accumulating during price drops")
        else:
            insights.append(f"🔴 Strong negative correlation ({correlation:+.2f}) - poor inventory timing!")
        # Check for position extremes
        valid_positions = [pos for pos in positions if pos is not None]
        if valid_positions:
            max_pos = max(valid_positions)
            min_pos = min(valid_positions)
            avg_pos = sum(valid_positions) / len(valid_positions)
            if max_pos - min_pos > avg_pos * 0.3:  # Position varied by >30%
                insights.append(f"📊 Position range: {min_pos:.3f} - {max_pos:.3f} {{ base_token }} (avg: {avg_pos:.3f})")
        return insights
    def get_parameter_changes():
        """Get parameter set change timeline"""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                pc.id,
                pc.timestamp,
                pc.old_parameter_set_id,
                pc.new_parameter_set_id,
                pc.change_type,
                pc.change_summary,
                pc.reason,
                pc.notes,
                ps_old.base_spread_bps as old_spread,
                ps_old.base_order_size as old_order_size,
                ps_old.description as old_description,
                ps_new.base_spread_bps as new_spread,
                ps_new.base_order_size as new_order_size,
                ps_new.description as new_description
            FROM parameter_changes pc
            LEFT JOIN parameter_sets ps_old ON pc.old_parameter_set_id = ps_old.id
            LEFT JOIN parameter_sets ps_new ON pc.new_parameter_set_id = ps_new.id
            WHERE pc.pair = ?
            ORDER BY pc.timestamp DESC
            LIMIT 20
        """, (PAIR,))
        rows = cursor.fetchall()
        conn.close()
        results = []
        for row in rows:
            results.append({
                'id': row['id'],
                'timestamp': row['timestamp'],
                'old_param_id': row['old_parameter_set_id'],
                'new_param_id': row['new_parameter_set_id'],
                'change_type': row['change_type'],
                'change_summary': row['change_summary'],
                'reason': row['reason'],
                'notes': row['notes'],
                'old_spread': row['old_spread'],
                'old_order_size': row['old_order_size'],
                'old_description': row['old_description'],
                'new_spread': row['new_spread'],
                'new_order_size': row['new_order_size'],
                'new_description': row['new_description']
            })
        return results
    @bp.route('/')
    def index():
        return render_template_string(DASHBOARD_HTML, pair_name=PAIR, base_token=PAIR.split("/")[0], quote_token=PAIR.split("/")[1] if "/" in PAIR else "USDC")
    
    @bp.route('/api/data')
    def get_data():
        """Get all dashboard data"""
        try:
            from flask import request
            from datetime import timezone
    
            now = datetime.now(timezone.utc)
    
            # Get window mode (static or rolling)
            window_mode = request.args.get('mode', 'static')
    
            # Get requested window durations (default to 1, 4, 8, 24 hours)
            windows_hours = request.args.get('windows', '1,4,8,24')
            window_list = []
    
            # Parse window list, supporting "all" keyword
            for h in windows_hours.split(','):
                h = h.strip().lower()
                if h == 'all':
                    window_list.append('all')
                elif h:
                    try:
                        window_list.append(float(h))
                    except ValueError:
                        continue
    
            print(f"[DASHBOARD DEBUG] Requested windows: {windows_hours}")
            print(f"[DASHBOARD DEBUG] Parsed window list: {window_list}")
            print(f"[DASHBOARD DEBUG] Window mode: {window_mode}")
    
            # Get current status
            status = get_current_status()
    
            # Get time window stats for each requested duration
            windows = {}
            window_labels = []
            window_ranges = {}  # Store actual time ranges for display
    
            for hours in window_list:
                if hours == 'all':
                    # For ALL, get stats from the very first record
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT MIN(timestamp) as first_time
                        FROM metrics_1min
                        WHERE pair = ?
                    """, (PAIR,))
                    first_row = cursor.fetchone()
                    conn.close()
    
                    if first_row and first_row['first_time']:
                        start_time_str = first_row['first_time']
                        stats = get_window_stats(start_time_str)
                        label = 'ALL'
                        window_ranges[label] = {'start': start_time_str, 'end': 'now'}
                    else:
                        stats = None
                        label = 'ALL'
                        window_ranges[label] = {'start': 'N/A', 'end': 'N/A'}
                else:
                    if window_mode == 'rolling':
                        # ROLLING WINDOWS: Exactly N hours back from now
                        start_time = now - timedelta(hours=hours)
                    else:
                        # STATIC WINDOWS: Round to hour boundaries
                        if hours == 24:
                            # 24H = start of current day (midnight UTC)
                            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        elif hours == 1:
                            # 1H = start of current hour
                            start_time = now.replace(minute=0, second=0, microsecond=0)
                        else:
                            # 4H, 8H = round down to N-hour boundary
                            # E.g., for 4H at 8:42, go back to 4:00 (nearest 4-hour mark)
                            hours_since_midnight = now.hour
                            boundary_hour = (hours_since_midnight // int(hours)) * int(hours)
                            start_time = now.replace(hour=boundary_hour, minute=0, second=0, microsecond=0)
    
                    # Format with space instead of T for SQLite compatibility
                    start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S+00:00')
                    stats = get_window_stats(start_time_str)
    
                    # Create nice label
                    if hours < 1:
                        label = f'{int(hours * 60)}min'
                    elif hours == int(hours):
                        label = f'{int(hours)}h'
                    else:
                        label = f'{hours}h'
    
                    window_ranges[label] = {
                        'start': start_time.strftime('%H:%M'),
                        'end': now.strftime('%H:%M'),
                        'hours': hours
                    }
    
                print(f"[DASHBOARD DEBUG] Window {label} (hours={hours}): stats={'found' if stats else 'None'}")
    
                # Always add the window, even if stats is None (will show "No data" in UI)
                windows[label] = stats
                window_labels.append(label)
    
            # Get parameter comparison
            param_comparison = get_parameter_comparison()
    
            # Get parameter changes timeline
            param_changes = get_parameter_changes()
    
            # Get drawdown info
            drawdown = get_drawdown()
    
            return jsonify({
                'success': True,
                'status': status,
                'windows': windows,
                'window_labels': window_labels,
                'window_ranges': window_ranges,
                'parameters': param_comparison,
                'parameter_changes': param_changes,
                'drawdown': drawdown,
                'updated_at': now.isoformat()
            })
    
        except Exception as e:
            import traceback
            return jsonify({
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            })
    
    @bp.route('/api/position_chart')
    def get_position_chart():
        """Get position and price chart data"""
        try:
            from flask import request
            from datetime import timezone
    
            now = datetime.now(timezone.utc)
    
            # Get requested window
            window = request.args.get('window', '4')
    
            # Calculate start time
            if window == 'all':
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MIN(timestamp) as first_time
                    FROM metrics_1min
                    WHERE pair = ?
                """, (PAIR,))
                first_row = cursor.fetchone()
                conn.close()
    
                if first_row and first_row['first_time']:
                    start_time_str = first_row['first_time']
                else:
                    return jsonify({'success': False, 'error': 'No data available'})
            else:
                try:
                    hours = float(window)
                    start_time = now - timedelta(hours=hours)
                    start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S+00:00')
                except ValueError:
                    return jsonify({'success': False, 'error': 'Invalid window parameter'})
    
            # Get position/price data
            chart_data = get_position_price_data(start_time_str)
    
            if not chart_data:
                return jsonify({'success': False, 'error': 'No data available for this time window'})
    
            return jsonify({
                'success': True,
                'chart_data': chart_data
            })
    
        except Exception as e:
            import traceback
            return jsonify({
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            })
    
    DASHBOARD_HTML = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>{{ pair_name }} Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
        <style>
            body {
                font-family: 'SF Mono', 'Monaco', 'Courier New', monospace;
                background: #0a0e27;
                color: #e0e0e0;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1600px;
                margin: 0 auto;
            }
            h1, h2 {
                color: #00ccff;
                border-bottom: 2px solid #00ccff;
                padding-bottom: 5px;
            }
            .section {
                background: #151b3d;
                padding: 20px;
                margin-bottom: 20px;
                border: 1px solid #00ccff;
                border-radius: 5px;
            }
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }
            .stat-card {
                background: #1a2140;
                padding: 15px;
                border-left: 3px solid #00ccff;
            }
            .stat-label {
                color: #888;
                font-size: 12px;
                text-transform: uppercase;
            }
            .stat-value {
                font-size: 24px;
                font-weight: bold;
                margin-top: 5px;
                color: #e0e0e0;
            }
            .positive { color: #00ff88; }
            .negative { color: #ff4444; }
            .neutral { color: #00ccff; }
            .warning { color: #ffaa00; }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                font-size: 13px;
            }
            th, td {
                padding: 8px;
                text-align: center;
                border-bottom: 1px solid #333;
            }
            th {
                background: #1a2140;
                color: #00ccff;
                font-weight: bold;
            }
            td:first-child {
                text-align: left;
            }
            .tooltip {
                position: relative;
                display: inline-block;
                border-bottom: 1px dotted #00ccff;
                cursor: help;
            }
            .tooltip .tooltiptext {
                visibility: hidden;
                width: 300px;
                background-color: #1a2140;
                color: #e0e0e0;
                text-align: left;
                border-radius: 6px;
                padding: 10px;
                position: absolute;
                z-index: 1000;
                bottom: 125%;
                left: 50%;
                margin-left: -150px;
                font-size: 11px;
                border: 1px solid #00ccff;
                line-height: 1.4;
                white-space: pre-line;
            }
            .tooltip:hover .tooltiptext {
                visibility: visible;
            }
            tr:hover {
                background: #1a2140;
            }
            .status-badge {
                display: inline-block;
                padding: 4px 10px;
                border-radius: 3px;
                font-size: 11px;
                font-weight: bold;
            }
            .badge-live { background: #00ff88; color: #000; }
            .badge-partial { background: #ffaa00; color: #000; }
            .badge-offline { background: #ff4444; color: #fff; }
            .timestamp {
                color: #666;
                font-size: 12px;
            }
            .window-header {
                background: #1a2140;
                font-weight: bold;
                color: #00ccff;
            }
            .metric-small {
                font-size: 11px;
                color: #888;
            }
            .highlight-current {
                background: #0f2818 !important;
            }
            .controls {
                margin-bottom: 15px;
                padding: 10px;
                background: #1a2140;
                border-radius: 3px;
            }
            .controls label {
                color: #888;
                margin-right: 10px;
            }
            .controls input {
                background: #151b3d;
                border: 1px solid #00ccff;
                color: #e0e0e0;
                padding: 5px 10px;
                border-radius: 3px;
            }
            .controls button {
                background: #00ccff;
                color: #000;
                border: none;
                padding: 6px 15px;
                border-radius: 3px;
                cursor: pointer;
                font-weight: bold;
                margin-left: 10px;
            }
            .controls button:hover {
                background: #00ff88;
            }
            .window-selector {
                display: flex;
                justify-content: flex-end;
                gap: 10px;
                margin-bottom: 20px;
            }
            .window-btn {
                background: #151b3d;
                color: #00ccff;
                border: 1px solid #00ccff;
                padding: 8px 20px;
                border-radius: 3px;
                cursor: pointer;
                font-weight: bold;
                font-size: 14px;
                transition: all 0.2s;
            }
            .window-btn:hover {
                background: #1a2140;
            }
            .window-btn.active {
                background: #00ccff;
                color: #000;
            }
            .mode-toggle {
                display: flex;
                gap: 0;
                border: 1px solid #00ccff;
                border-radius: 3px;
                overflow: hidden;
                margin-right: 15px;
            }
            .mode-btn {
                background: #151b3d;
                color: #00ccff;
                border: none;
                padding: 8px 15px;
                cursor: pointer;
                font-weight: bold;
                font-size: 12px;
                transition: all 0.2s;
            }
            .mode-btn.active {
                background: #00ccff;
                color: #000;
            }
            .mode-btn:hover:not(.active) {
                background: #1a2140;
            }
            .summary-grid {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 15px;
                margin-bottom: 20px;
            }
            .summary-card {
                background: #151b3d;
                padding: 20px;
                border-radius: 5px;
                border: 1px solid #00ccff;
            }
            .summary-card h3 {
                font-size: 12px;
                color: #00ccff;
                text-transform: uppercase;
                margin: 0 0 15px 0;
                font-weight: normal;
            }
            .summary-main {
                font-size: 32px;
                font-weight: bold;
                margin-bottom: 5px;
            }
            .summary-sub {
                font-size: 12px;
                color: #888;
                margin-top: 8px;
            }
            .summary-row {
                display: flex;
                justify-content: space-between;
                margin-top: 8px;
                font-size: 13px;
            }
            .alerts-container {
                background: #1a1410;
                border: 2px solid #ff4444;
                border-radius: 5px;
                padding: 15px;
                margin-bottom: 20px;
                display: none;
            }
            .alerts-container.active {
                display: block;
            }
            .alerts-header {
                color: #ff4444;
                font-weight: bold;
                font-size: 14px;
                margin-bottom: 10px;
                text-transform: uppercase;
            }
            .alert-item {
                background: #2a1f1a;
                border-left: 3px solid #ff4444;
                padding: 10px 15px;
                margin-bottom: 8px;
                border-radius: 3px;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .alert-item:last-child {
                margin-bottom: 0;
            }
            .alert-icon {
                font-size: 18px;
            }
            .alert-warning {
                border-left-color: #ffaa00;
            }
            .alert-warning .alert-icon {
                color: #ffaa00;
            }
            .alert-critical {
                border-left-color: #ff4444;
            }
            .alert-critical .alert-icon {
                color: #ff4444;
            }
            .alert-info {
                border-left-color: #00ccff;
            }
            .alert-info .alert-icon {
                color: #00ccff;
            }
            .timeline-item {
                background: #1a2140;
                border-left: 3px solid #00ccff;
                padding: 15px;
                margin-bottom: 10px;
                border-radius: 3px;
            }
            .timeline-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .timeline-timestamp {
                color: #00ccff;
                font-weight: bold;
                font-size: 14px;
            }
            .timeline-reason {
                background: #151b3d;
                padding: 3px 8px;
                border-radius: 3px;
                font-size: 11px;
                color: #888;
            }
            .timeline-change {
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 13px;
                margin-top: 8px;
            }
            .timeline-arrow {
                color: #00ccff;
                margin: 0 10px;
            }
            .timeline-old {
                color: #888;
            }
            .timeline-new {
                color: #00ff88;
            }
            .chart-container {
                background: #151b3d;
                padding: 20px;
                border-radius: 5px;
                margin-bottom: 15px;
                position: relative;
                height: 400px;
            }
            .chart-controls {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }
            .chart-window-btn {
                background: #151b3d;
                color: #00ccff;
                border: 1px solid #00ccff;
                padding: 6px 15px;
                border-radius: 3px;
                cursor: pointer;
                font-weight: bold;
                font-size: 12px;
                transition: all 0.2s;
            }
            .chart-window-btn:hover {
                background: #1a2140;
            }
            .chart-window-btn.active {
                background: #00ccff;
                color: #000;
            }
            .chart-insights {
                background: #1a2140;
                padding: 15px;
                border-radius: 3px;
                margin-top: 15px;
                border-left: 3px solid #00ccff;
            }
            .chart-insight-item {
                font-size: 13px;
                margin-bottom: 8px;
                color: #e0e0e0;
            }
            .chart-insight-item:last-child {
                margin-bottom: 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h1 style="margin: 0;">🤖 {{ pair_name }} Dashboard</h1>
                <div style="display: flex; align-items: center;">
                    <div class="mode-toggle">
                        <button class="mode-btn active" onclick="setWindowMode('static')">STATIC</button>
                        <button class="mode-btn" onclick="setWindowMode('rolling')">ROLLING</button>
                    </div>
                    <div class="window-selector">
                        <button class="window-btn active" data-window="1" onclick="selectWindow(1)">1H</button>
                        <button class="window-btn" data-window="4" onclick="selectWindow(4)">4H</button>
                        <button class="window-btn" data-window="8" onclick="selectWindow(8)">8H</button>
                        <button class="window-btn" data-window="24" onclick="selectWindow(24)">24H</button>
                        <button class="window-btn" data-window="all" onclick="selectWindow('all')">ALL</button>
                    </div>
                </div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <p class="timestamp">Last updated: <span id="updated-at">Loading...</span></p>
                <p class="timestamp" style="color: #00ccff;">Window: <span id="window-range">Loading...</span></p>
            </div>
    
            <!-- Alerts Section -->
            <div id="alerts-container" class="alerts-container">
                <div class="alerts-header">⚠️ ACTIVE ALERTS</div>
                <div id="alerts-list"></div>
            </div>
    
            <!-- Summary Cards Grid -->
            <div class="summary-grid">
                <div class="summary-card">
                    <h3>💰 Total P&L</h3>
                    <div class="summary-main" id="sum-total-pnl">...</div>
                    <div class="summary-sub" id="sum-total-pct">...</div>
                    <div class="summary-row" style="margin-top: 10px;">
                        <span>Trading P&L</span>
                        <span id="sum-trading-pnl">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Market P&L</span>
                        <span id="sum-market-pnl">...</span>
                    </div>
                    <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #2a3359; font-size: 11px; color: #888; text-align: center;">
                        <div style="margin-bottom: 5px;">{{ pair_name }} on Hyperliquid</div>
                        <div style="margin-bottom: 5px;">24h Market Vol: <span id="sum-market-vol">...</span></div>
                        <div>Period: <span id="sum-period-price">...</span></div>
                        <div id="sum-price-change" style="margin-top: 3px;">...</div>
                    </div>
                </div>
    
                <div class="summary-card">
                    <h3>📊 Trading Activity</h3>
                    <div class="summary-main" id="sum-fills">...</div>
                    <div style="font-size: 13px; color: #888; margin-top: 5px;">Volume:</div>
                    <div class="summary-main" id="sum-volume" style="font-size: 28px; margin-top: 0px;">...</div>
                    <div class="summary-row" style="margin-top: 10px;">
                        <span>Buys / Sells:</span>
                        <span id="sum-buysells">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Fills/Hour:</span>
                        <span id="sum-fillrate">...</span>
                    </div>
                </div>
    
                <div class="summary-card">
                    <h3>📈 Strategy Analysis</h3>
                    <div class="summary-row">
                        <span class="tooltip">Buy & Hold P&L:
                            <span class="tooltiptext">What you'd have made putting all capital into {{ base_token }} at start and holding</span>
                        </span>
                        <span id="sum-buyhold">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Alpha:
                            <span class="tooltiptext">How much better/worse you did vs passive holding. Positive = you beat buy & hold!</span>
                        </span>
                        <span id="sum-alpha">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Market Direction:
                            <span class="tooltiptext">Profit from inventory change × price movement. High % = you got lucky with timing</span>
                        </span>
                        <span id="sum-direction">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Trading Skill:
                            <span class="tooltiptext">Pure spread capture profit independent of price moves. High % = skilled MM</span>
                        </span>
                        <span id="sum-skill">...</span>
                    </div>
                </div>
    
                <div class="summary-card">
                    <h3>🎯 Fill Quality</h3>
                    <div class="summary-row">
                        <span>Status</span>
                        <span id="sum-fill-status">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Avg Fill Size</span>
                        <span id="sum-avg-size">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Target Fill
                            <span class="tooltiptext">What % of your target order size you're actually getting filled. Higher = less competition.</span>
                        </span>
                        <span id="sum-target-fill">...</span>
                    </div>
                </div>
    
                <div class="summary-card">
                    <h3>💼 Current Balances</h3>
                    <div class="summary-row">
                        <span>{{ base_token }} Total</span>
                        <span id="sum-xmr-total">...</span>
                    </div>
                    <div class="summary-row">
                        <span>{{ quote_token }} Total</span>
                        <span id="sum-usdc-total">...</span>
                    </div>
                    <div class="summary-row">
                        <span>{{ base_token }} Price</span>
                        <span id="sum-price">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Total Capital</span>
                        <span id="sum-capital">...</span>
                    </div>
                </div>
    
                <div class="summary-card">
                    <h3>📈 Performance</h3>
                    <div class="summary-row">
                        <span>Net Fees:</span>
                        <span id="sum-fees">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Hourly P&L:</span>
                        <span id="sum-hourly">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Monthly ROI:</span>
                        <span id="sum-monthly-roi">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Duration:</span>
                        <span id="sum-duration">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Drawdown:
                            <span class="tooltiptext">Current decline from peak portfolio value. 0% = at all-time high. Negative % = below peak.</span>
                        </span>
                        <span id="sum-drawdown">...</span>
                    </div>
                </div>
    
                <div class="summary-card">
                    <h3>🛡️ Toxicity Monitor</h3>
                    <div class="summary-row">
                        <span class="tooltip">Avg Markout 5s/30s:
                            <span class="tooltiptext">How price moves after fills. Positive = good, negative = toxic (getting picked off)</span>
                        </span>
                        <span id="sum-markout">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Negative Fills:
                            <span class="tooltiptext">% of fills where price moved against you within 30s. <40% = good, >70% = toxic</span>
                        </span>
                        <span id="sum-neg-fills">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Buy/Sell Imbal:
                            <span class="tooltiptext">Are you getting hit mostly on one side? >75% one-sided = toxic</span>
                        </span>
                        <span id="sum-imbalance">...</span>
                    </div>
                </div>
    
                <div class="summary-card">
                    <h3>⚙️ Bot Settings</h3>
                    <div class="summary-row">
                        <span>Order Size:</span>
                        <span id="sum-order-size">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Spread:</span>
                        <span id="sum-spread">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Target Position:</span>
                        <span id="sum-target-pos">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Max Position:</span>
                        <span id="sum-max-pos">...</span>
                    </div>
                    <div class="summary-row">
                        <span>Update Interval:</span>
                        <span id="sum-interval">...</span>
                    </div>
                    <div class="summary-row">
                        <span class="tooltip">Quote Refresh:
                            <span class="tooltiptext">Price movement threshold that forces new quotes to be placed</span>
                        </span>
                        <span id="sum-quote-refresh">...</span>
                    </div>
                </div>
            </div>
    
            <!-- Current Status -->
            <div class="section">
                <h2>📊 Current Status</h2>
                <div class="grid">
                    <div class="stat-card">
                        <div class="stat-label">Bot Status</div>
                        <div class="stat-value" id="bot-status">...</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Portfolio Value</div>
                        <div class="stat-value" id="portfolio-value">...</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">{{ base_token }} Balance</div>
                        <div class="stat-value" id="xmr-balance">...</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">{{ quote_token }} Balance</div>
                        <div class="stat-value" id="usdc-balance">...</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Mid Price</div>
                        <div class="stat-value" id="mid-price">...</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Our Spread</div>
                        <div class="stat-value" id="our-spread">...</div>
                    </div>
                </div>
            </div>
    
            <!-- Parameter Changes Timeline -->
            <div class="section">
                <h2>⚙️ Configuration Changes Timeline</h2>
                <div id="param-changes-container">
                    <p style="color: #888;">Loading parameter changes...</p>
                </div>
            </div>
    
            <!-- Position & Price Tracking Chart -->
            <div class="section">
                <h2>📈 Position & Price Tracking</h2>
                <div class="chart-controls">
                    <div>
                        <span style="color: #888; font-size: 13px; margin-right: 10px;">Time Window:</span>
                        <button class="chart-window-btn active" data-chart-window="1" onclick="selectChartWindow(1)">1H</button>
                        <button class="chart-window-btn" data-chart-window="4" onclick="selectChartWindow(4)">4H</button>
                        <button class="chart-window-btn" data-chart-window="8" onclick="selectChartWindow(8)">8H</button>
                        <button class="chart-window-btn" data-chart-window="24" onclick="selectChartWindow(24)">24H</button>
                        <button class="chart-window-btn" data-chart-window="all" onclick="selectChartWindow('all')">ALL</button>
                    </div>
                </div>
                <div class="chart-container">
                    <canvas id="position-chart"></canvas>
                </div>
                <div class="chart-insights" id="chart-insights">
                    <div class="chart-insight-item">💡 Loading correlation analysis...</div>
                </div>
            </div>
    
            <!-- Time Windows -->
            <div class="section">
                <h2>📈 Performance Windows</h2>
                <div class="controls">
                    <label>Time Windows (hours, comma-separated, or "all"):</label>
                    <input type="text" id="windows-input" value="1,4,8,24,all" onkeypress="if(event.key==='Enter') updateWindows();" />
                    <button type="button" onclick="updateWindows(); return false;">Update</button>
                </div>
                <table id="windows-table">
                    <thead>
                        <tr>
                            <th>Window</th>
                            <th>Duration</th>
                            <th>{{ base_token }} Price<br><span class="metric-small">Start → End</span></th>
                            <th>Fills</th>
                            <th>Volume</th>
                            <th>Start {{ base_token }}</th>
                            <th>End {{ base_token }}</th>
                            <th>Δ {{ base_token }}</th>
                            <th>Start {{ quote_token }}</th>
                            <th>End {{ quote_token }}</th>
                            <th>Δ {{ quote_token }}</th>
                            <th><span class="tooltip">Trading PnL<br><span class="metric-small">(spreads)</span>
                                <span class="tooltiptext">Trading PnL = (End_{{ base_token }} × Start_Price + End_USDC) - (Start_{{ base_token }} × Start_Price + Start_USDC)
    
    Profit from trading at better prices than you started with. This shows the value gained from buying low and selling high at the spread, excluding price movement. Positive means you traded profitably.</span>
                            </span></th>
                            <th><span class="tooltip">Market PnL<br><span class="metric-small">(price Δ)</span>
                                <span class="tooltiptext">Market PnL = (End_{{ base_token }} × End_Price) - (End_{{ base_token }} × Start_Price)
    
    Unrealized profit/loss from price movement on your remaining inventory. If price goes up and you're holding {{ base_token }}, this is positive. If price goes down, this is negative. This is independent of your trading.</span>
                            </span></th>
                            <th><span class="tooltip">Total PnL
                                <span class="tooltiptext">Total PnL = Trading PnL + Market PnL
    = (End_{{ base_token }} × End_Price + End_USDC) - (Start_{{ base_token }} × Start_Price + Start_USDC)
    
    Your actual total portfolio value change. This is the real profit or loss for this time window.</span>
                            </span></th>
                            <th><span class="tooltip">$/Hour
                                <span class="tooltiptext">$/Hour = Trading PnL ÷ Hours
    
    Trading PnL per hour. Shows how much profit you're making from spreads on an hourly basis. Use this to compare profitability across different time windows.</span>
                            </span></th>
                        </tr>
                    </thead>
                    <tbody id="windows-body">
                        <tr><td colspan="15">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
    
            <!-- Parameter Comparison -->
            <div class="section">
                <h2>⚙️ Configuration Performance</h2>
                <table id="params-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Spread</th>
                            <th>Size</th>
                            <th>Skew</th>
                            <th>Runtime</th>
                            <th>Fills</th>
                            <th>Net PnL</th>
                            <th>$/Hour</th>
                        </tr>
                    </thead>
                    <tbody id="params-body">
                        <tr><td colspan="8">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    
        <script>
            let currentWindows = '1,4,8,24,all';
            let selectedWindow = 1; // Default to 1H
            let windowMode = 'static'; // 'static' or 'rolling'
            let cachedData = null;
    
            function setWindowMode(mode) {
                console.log('Setting window mode:', mode);
                windowMode = mode;
    
                // Update button states
                document.querySelectorAll('.mode-btn').forEach(btn => {
                    btn.classList.remove('active');
                });
                event.target.classList.add('active');
    
                // Refresh data with new mode
                updateDashboard();
            }
    
            function selectWindow(windowHours) {
                console.log('Selecting window:', windowHours);
                selectedWindow = windowHours;
    
                // Update button states
                document.querySelectorAll('.window-btn').forEach(btn => {
                    btn.classList.remove('active');
                });
                document.querySelector(`[data-window="${windowHours}"]`).classList.add('active');
    
                // Update summary cards with selected window data
                updateSummaryCards();
            }
    
            function updateWindows() {
                const input = document.getElementById('windows-input').value.trim();
                currentWindows = input;
                console.log('Updating windows to:', currentWindows);
                updateDashboard();
                return false; // Prevent any default action
            }
    
            function updateSummaryCards() {
                if (!cachedData || !cachedData.windows) return;
    
                // Determine which window to display
                let windowLabel;
                if (selectedWindow === 'all') {
                    windowLabel = 'ALL';
                } else {
                    windowLabel = selectedWindow + 'h';
                }
    
                console.log('Updating summary cards for window:', windowLabel);
    
                // Get the window data
                const w = cachedData.windows[windowLabel];
    
                if (!w) {
                    console.log('No data for selected window');
                    return;
                }
    
                const s = cachedData.status;
    
                // Update window range indicator using backend data
                let rangeText = '';
                if (selectedWindow === 'all') {
                    rangeText = 'All Time';
                } else {
                    const rangeData = cachedData.window_ranges?.[windowLabel];
                    if (rangeData && rangeData.start && rangeData.end) {
                        rangeText = `${rangeData.start} - ${rangeData.end} (${windowMode} ${selectedWindow}H)`;
                    } else {
                        rangeText = `${windowMode} ${selectedWindow}H window`;
                    }
                }
                document.getElementById('window-range').textContent = rangeText;
    
                // Total P&L card (matching old dashboard)
                document.getElementById('sum-total-pnl').innerHTML = formatPnL(w.total_pnl);
                document.getElementById('sum-total-pnl').className = 'summary-main ' + getPnLClass(w.total_pnl);
    
                const totalPct = s && s.total_value_usd ? (w.total_pnl / s.total_value_usd * 100).toFixed(2) : 0;
                const projectedDaily = w.hours > 0 ? (w.total_pnl / w.hours * 24).toFixed(2) : 0;
                document.getElementById('sum-total-pct').innerHTML = `${totalPct >= 0 ? '+' : ''}${totalPct}% | $${projectedDaily}/day projected`;
    
                const tradingPct = s && s.total_value_usd ? (w.realized_pnl / s.total_value_usd * 100).toFixed(1) : 0;
                document.getElementById('sum-trading-pnl').innerHTML = `${formatPnL(w.realized_pnl)} <span style="color: #888;">(${tradingPct >= 0 ? '+' : ''}${tradingPct}%)</span>`;
                document.getElementById('sum-trading-pnl').className = getPnLClass(w.realized_pnl);
    
                const marketPct = s && s.total_value_usd ? (w.unrealized_pnl / s.total_value_usd * 100).toFixed(1) : 0;
                document.getElementById('sum-market-pnl').innerHTML = `${formatPnL(w.unrealized_pnl)} <span style="color: #888;">(${marketPct >= 0 ? '+' : ''}${marketPct}%)</span>`;
                document.getElementById('sum-market-pnl').className = getPnLClass(w.unrealized_pnl);
    
                // Market info
                document.getElementById('sum-market-vol').innerHTML = '$' + w.volume.toFixed(0);
                document.getElementById('sum-period-price').innerHTML = `$${w.start_price.toFixed(2)} → $${w.end_price.toFixed(2)}`;
                const priceChangePct = ((w.end_price - w.start_price) / w.start_price * 100).toFixed(2);
                document.getElementById('sum-price-change').innerHTML = `<span class="${getPnLClass(w.end_price - w.start_price)}">${priceChangePct >= 0 ? '+' : ''}${priceChangePct}%</span>`;
                document.getElementById('sum-price-change').className = getPnLClass(w.end_price - w.start_price);
    
                // Trading Activity card
                document.getElementById('sum-fills').innerHTML = w.fills + ' fills';
                document.getElementById('sum-volume').innerHTML = '$' + w.volume.toFixed(0);
                document.getElementById('sum-buysells').innerHTML = `${w.buy_fills} / ${w.sell_fills}`;
                const fillRate = w.hours > 0 ? (w.fills / w.hours).toFixed(1) : 0;
                document.getElementById('sum-fillrate').innerHTML = fillRate;
    
                // Strategy Analysis card (matching old dashboard calculations)
                const startingValue = w.start_value;
                const allInXmr = startingValue / w.start_price; // Convert all capital to {{ base_token }} at start
                const buyHoldFinalValue = allInXmr * w.end_price;
                const buyHoldPnl = buyHoldFinalValue - startingValue;
                const alpha = w.total_pnl - buyHoldPnl;
    
                // P&L Attribution
                const inventoryChangeXmr = w.base_delta;
                const priceChange = w.end_price - w.start_price;
                const marketDirectionPnl = inventoryChangeXmr * priceChange; // Profit from inventory × price movement
                const tradingSkillPnl = w.realized_pnl - marketDirectionPnl; // Spread capture
    
                // Calculate percentages
                const marketDirectionPct = w.realized_pnl !== 0 ? (marketDirectionPnl / Math.abs(w.realized_pnl) * 100) : 0;
                const tradingSkillPct = w.realized_pnl !== 0 ? (tradingSkillPnl / Math.abs(w.realized_pnl) * 100) : 0;
    
                document.getElementById('sum-buyhold').innerHTML = formatPnL(buyHoldPnl);
                document.getElementById('sum-buyhold').className = getPnLClass(buyHoldPnl);
                document.getElementById('sum-alpha').innerHTML = formatPnL(alpha);
                document.getElementById('sum-alpha').className = getPnLClass(alpha);
                document.getElementById('sum-direction').innerHTML = `${formatPnL(marketDirectionPnl)} <span style="color: #888;">(${Math.abs(marketDirectionPct).toFixed(0)}%)</span>`;
                document.getElementById('sum-direction').className = getPnLClass(marketDirectionPnl);
                document.getElementById('sum-skill').innerHTML = `${formatPnL(tradingSkillPnl)} <span style="color: #888;">(${Math.abs(tradingSkillPct).toFixed(0)}%)</span>`;
                document.getElementById('sum-skill').className = getPnLClass(tradingSkillPnl);
    
                // Fill Quality card
                let avgFillSizeBase = 0;
                if (w.fills > 0 && w.volume > 0) {
                    // Calculate average base amount per fill
                    // volume is in quote (USDC), so divide by avg price to get base amount
                    const avgPrice = w.avg_price || w.end_price;
                    avgFillSizeBase = (w.volume / avgPrice) / w.fills;
                }
    
                // Get target order size from bot settings
                let targetOrderSize = 0.2; // Default
                if (s && cachedData.parameters && cachedData.parameters.length > 0) {
                    const currentParam = cachedData.parameters.find(p => p.id === s.parameter_set_id);
                    if (currentParam) {
                        targetOrderSize = currentParam.order_size;
                    }
                }
    
                const avgSizeXmr = avgFillSizeBase;
                const targetPct = avgFillSizeBase > 0 ? (avgFillSizeBase / targetOrderSize * 100) : 0;
    
                // Determine fill quality status
                let fillStatus = 'N/A';
                let fillStatusClass = 'neutral';
                if (targetPct > 0) {
                    if (targetPct >= 80) {
                        fillStatus = 'Excellent';
                        fillStatusClass = 'positive';
                    } else if (targetPct >= 60) {
                        fillStatus = 'Good';
                        fillStatusClass = 'positive';
                    } else if (targetPct >= 40) {
                        fillStatus = 'Fair';
                        fillStatusClass = 'warning';
                    } else {
                        fillStatus = 'Poor';
                        fillStatusClass = 'negative';
                    }
                }
    
                document.getElementById('sum-fill-status').innerHTML = fillStatus;
                document.getElementById('sum-fill-status').className = fillStatusClass;
                document.getElementById('sum-avg-size').innerHTML = avgSizeXmr > 0 ? avgSizeXmr.toFixed(4) + ' {{ base_token }}' : 'N/A';
                document.getElementById('sum-target-fill').innerHTML = targetPct > 0 ? targetPct.toFixed(0) + '% of ' + targetOrderSize : 'N/A';
    
                // Current Balances card (matching old dashboard with start → end arrows)
                if (s) {
                    document.getElementById('sum-xmr-total').innerHTML = `<span style="color: #666;">${w.start_base.toFixed(4)} →</span> ${w.end_base.toFixed(4)}`;
                    document.getElementById('sum-usdc-total').innerHTML = `<span style="color: #666;">$${w.start_quote.toFixed(2)} →</span> $${w.end_quote.toFixed(2)}`;
                    document.getElementById('sum-price').innerHTML = `<span style="color: #666;">$${w.start_price.toFixed(2)} →</span> $${w.end_price.toFixed(2)}`;
                    document.getElementById('sum-capital').innerHTML = `<span style="color: #666;">$${w.start_value.toFixed(2)} →</span> $${w.end_value.toFixed(2)}`;
                }
    
                // Performance card
                document.getElementById('sum-fees').innerHTML = '-$' + w.fees.toFixed(2);
                document.getElementById('sum-fees').className = 'negative';
                document.getElementById('sum-hourly').innerHTML = formatPnL(w.pnl_per_hour) + '/hr';
                document.getElementById('sum-hourly').className = getPnLClass(w.pnl_per_hour);
                const monthlyRoi = s && s.total_value_usd && w.hours > 0 ?
                    (w.pnl_per_hour * 24 * 30 / s.total_value_usd * 100).toFixed(1) : 0;
                document.getElementById('sum-monthly-roi').innerHTML = `${monthlyRoi}%/mo`;
                document.getElementById('sum-duration').innerHTML = w.hours.toFixed(1) + ' hrs';
    
                // Drawdown
                if (cachedData.drawdown) {
                    const dd = cachedData.drawdown;
                    const ddPct = dd.drawdown_pct;
                    const ddClass = ddPct >= -5 ? 'positive' : ddPct >= -15 ? 'warning' : 'negative';
                    document.getElementById('sum-drawdown').innerHTML = `<span class="${ddClass}">${ddPct.toFixed(1)}%</span>`;
                    document.getElementById('sum-drawdown').className = ddClass;
                } else {
                    document.getElementById('sum-drawdown').innerHTML = 'N/A';
                    document.getElementById('sum-drawdown').className = 'neutral';
                }
    
                // Toxicity Monitor card
                const toxicity = w.toxicity || {};
    
                if (toxicity.insufficient_data) {
                    document.getElementById('sum-markout').innerHTML = 'N/A';
                    document.getElementById('sum-neg-fills').innerHTML = 'N/A';
                } else {
                    // Avg Markout (5s / 30s)
                    const markout5s = toxicity.avg_markout_5s || 0;
                    const markout30s = toxicity.avg_markout_30s || 0;
                    document.getElementById('sum-markout').innerHTML =
                        `<span class="${getToxicityClass(markout30s)}">${markout5s >= 0 ? '+' : ''}${markout5s.toFixed(1)}</span> / ` +
                        `<span class="${getToxicityClass(markout30s)}">${markout30s >= 0 ? '+' : ''}${markout30s.toFixed(1)}</span> bps`;
    
                    // Negative Fills %
                    const negFills = toxicity.pct_negative_30s || 0;
                    document.getElementById('sum-neg-fills').innerHTML = `<span class="${getToxicityClass(-negFills)}">${negFills.toFixed(0)}%</span>`;
                }
    
                // Buy/Sell Imbalance
                const buyPct = toxicity.buy_pct || 50;
                const sellPct = toxicity.sell_pct || 50;
                const imbalance = toxicity.imbalance_score || 0;
    
                document.getElementById('sum-imbalance').innerHTML = buyPct.toFixed(0) + '% / ' + sellPct.toFixed(0) + '%';
                const imbalanceEl = document.getElementById('sum-imbalance');
                if (imbalance < 30) {
                    imbalanceEl.className = 'positive';
                } else if (imbalance < 70) {
                    imbalanceEl.className = 'warning';
                } else {
                    imbalanceEl.className = 'negative';
                }
    
                // Bot Settings card
                if (s && cachedData.parameters && cachedData.parameters.length > 0) {
                    const currentParam = cachedData.parameters.find(p => p.id === s.parameter_set_id);
                    if (currentParam) {
                        document.getElementById('sum-order-size').innerHTML = currentParam.order_size;
                        document.getElementById('sum-spread').innerHTML = currentParam.spread_bps + ' bps';
                        document.getElementById('sum-target-pos').innerHTML = (currentParam.target_position || 0) + ' {{ base_token }}';
                        document.getElementById('sum-max-pos').innerHTML = (currentParam.max_position || 0) + ' {{ base_token }}';
                        document.getElementById('sum-interval').innerHTML = currentParam.update_interval ? currentParam.update_interval + 's' : 'N/A';
                        document.getElementById('sum-quote-refresh').innerHTML = (currentParam.quote_refresh_bps || 0) + ' bps';
                    }
                }
    
                // Check for alerts
                checkAlerts(w, s, toxicity, cachedData.parameters);
            }
    
            function checkAlerts(windowData, status, toxicity, parameters) {
                const alerts = [];
    
                // 1. High Toxicity Alert (>70% negative fills)
                if (!toxicity.insufficient_data && toxicity.pct_negative_30s > 70) {
                    alerts.push({
                        type: 'critical',
                        icon: '🔴',
                        message: `TOXIC FILLS: ${toxicity.pct_negative_30s.toFixed(0)}% of fills are negative (getting picked off!)`
                    });
                } else if (!toxicity.insufficient_data && toxicity.pct_negative_30s > 50) {
                    alerts.push({
                        type: 'warning',
                        icon: '⚠️',
                        message: `Elevated toxicity: ${toxicity.pct_negative_30s.toFixed(0)}% of fills are negative`
                    });
                }
    
                // 2. Position exceeds max (if we can determine current position and max)
                if (status && parameters && parameters.length > 0) {
                    const currentParam = parameters.find(p => p.id === status.parameter_set_id);
                    if (currentParam && currentParam.max_position) {
                        const currentPosition = Math.abs(status.base_total || 0);
                        const maxPosition = currentParam.max_position;
                        if (currentPosition > maxPosition * 0.95) {
                            alerts.push({
                                type: 'critical',
                                icon: '⚡',
                                message: `POSITION LIMIT: ${currentPosition.toFixed(2)} XMR (${(currentPosition/maxPosition*100).toFixed(0)}% of max ${maxPosition})`
                            });
                        }
                    }
                }
    
                // 3. No fills in selected window (if window is >30 min)
                if (windowData.hours >= 0.5 && windowData.fills === 0) {
                    alerts.push({
                        type: 'warning',
                        icon: '😴',
                        message: `NO FILLS: Bot hasn't filled in ${windowData.hours.toFixed(1)} hours - check if stuck or spread too wide`
                    });
                }
    
                // 4. Spread widened significantly (>2x normal)
                if (status && status.our_bid_price && status.our_ask_price && status.mid_price) {
                    const ourSpreadBps = ((status.our_ask_price - status.our_bid_price) / status.mid_price) * 10000;
                    if (parameters && parameters.length > 0) {
                        const currentParam = parameters.find(p => p.id === status.parameter_set_id);
                        if (currentParam && currentParam.spread_bps) {
                            const normalSpread = currentParam.spread_bps;
                            if (ourSpreadBps > normalSpread * 2) {
                                alerts.push({
                                    type: 'info',
                                    icon: '📏',
                                    message: `WIDE SPREAD: Current spread ${ourSpreadBps.toFixed(0)} bps (>2x normal ${normalSpread} bps)`
                                });
                            }
                        }
                    }
                }
    
                // 5. Large negative markout
                if (!toxicity.insufficient_data && toxicity.avg_markout_30s < -10) {
                    alerts.push({
                        type: 'warning',
                        icon: '📉',
                        message: `ADVERSE SELECTION: Avg 30s markout is ${toxicity.avg_markout_30s.toFixed(1)} bps (price moving against fills)`
                    });
                }
    
                // Display alerts
                const alertsContainer = document.getElementById('alerts-container');
                const alertsList = document.getElementById('alerts-list');
    
                if (alerts.length > 0) {
                    alertsList.innerHTML = alerts.map(alert => `
                        <div class="alert-item alert-${alert.type}">
                            <span class="alert-icon">${alert.icon}</span>
                            <span>${alert.message}</span>
                        </div>
                    `).join('');
                    alertsContainer.classList.add('active');
                } else {
                    alertsContainer.classList.remove('active');
                }
            }
    
    
            function formatPnL(value) {
                const sign = value >= 0 ? '+' : '';
                return sign + '$' + value.toFixed(2);
            }
    
            function getPnLClass(value) {
                return value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral';
            }
    
            function getToxicityClass(markoutBps) {
                // Positive markout = good (green)
                // Negative markout = toxic (red)
                if (markoutBps > 0) return 'positive';
                if (markoutBps > -5) return 'neutral';
                if (markoutBps > -10) return 'warning';
                return 'negative';
            }
    
            function updateDashboard() {
                fetch('api/data?windows=' + encodeURIComponent(currentWindows) + '&mode=' + windowMode)
                    .then(r => r.json())
                    .then(data => {
                        if (!data.success) {
                            console.error('Error:', data.error);
                            return;
                        }
    
                        // Cache data for summary cards
                        cachedData = data;
    
                        // Update timestamp
                        document.getElementById('updated-at').textContent = new Date(data.updated_at).toLocaleString();
    
                        // Update summary cards
                        updateSummaryCards();
    
                        // Update status
                        const s = data.status;
                        if (s) {
                            const bidLive = s.bid_live;
                            const askLive = s.ask_live;
                            let status = '';
                            if (bidLive && askLive) status = '<span class="status-badge badge-live">BOTH SIDES LIVE</span>';
                            else if (bidLive || askLive) status = '<span class="status-badge badge-partial">ONE SIDE LIVE</span>';
                            else status = '<span class="status-badge badge-offline">OFFLINE</span>';
                            document.getElementById('bot-status').innerHTML = status;
    
                            document.getElementById('portfolio-value').innerHTML = '$' + (s.total_value_usd || 0).toFixed(2);
                            document.getElementById('xmr-balance').innerHTML = (s.base_total || 0).toFixed(3) + ' {{ base_token }}';
                            document.getElementById('usdc-balance').innerHTML = '$' + (s.quote_total || 0).toFixed(2);
                            document.getElementById('mid-price').innerHTML = '$' + (s.mid_price || 0).toFixed(2);
    
                            if (s.our_bid_price && s.our_ask_price) {
                                const spread = s.our_ask_price - s.our_bid_price;
                                const spreadBps = (spread / s.mid_price * 10000).toFixed(0);
                                document.getElementById('our-spread').innerHTML = spreadBps + ' bps';
                            }
                        }
    
                        // Update windows
                        const windows = data.windows;
                        let windowsHtml = '';
    
                        for (const label of data.window_labels) {
                            const w = windows[label];
                            if (!w) {
                                console.log('Warning: No data for window', label);
                                windowsHtml += `
                                    <tr>
                                        <td><strong>Last ${label}</strong></td>
                                        <td colspan="14" class="neutral">No data available for this time window</td>
                                    </tr>
                                `;
                                continue;
                            }
    
                            const tradingPnlClass = w.realized_pnl > 0 ? 'positive' : w.realized_pnl < 0 ? 'negative' : '';
                            const marketPnlClass = w.unrealized_pnl > 0 ? 'positive' : w.unrealized_pnl < 0 ? 'negative' : '';
                            const totalPnlClass = w.total_pnl > 0 ? 'positive' : w.total_pnl < 0 ? 'negative' : '';
                            const baseDeltaClass = w.base_delta > 0 ? 'positive' : w.base_delta < 0 ? 'negative' : '';
                            const quoteDeltaClass = w.quote_delta > 0 ? 'positive' : w.quote_delta < 0 ? 'negative' : '';
    
                            // Price change
                            const priceChange = w.end_price - w.start_price;
                            const priceChangePct = (priceChange / w.start_price * 100);
                            const priceChangeClass = priceChange > 0 ? 'positive' : priceChange < 0 ? 'negative' : '';
    
                            windowsHtml += `
                                <tr>
                                    <td><strong>Last ${label}</strong></td>
                                    <td>${w.hours.toFixed(1)}h</td>
                                    <td>
                                        $${w.start_price.toFixed(2)} → $${w.end_price.toFixed(2)}
                                        <br><span class="metric-small ${priceChangeClass}">${priceChange >= 0 ? '+' : ''}$${priceChange.toFixed(2)} (${priceChangePct >= 0 ? '+' : ''}${priceChangePct.toFixed(2)}%)</span>
                                    </td>
                                    <td>${w.fills} <span class="metric-small">(${w.buy_fills}/${w.sell_fills})</span></td>
                                    <td>$${w.volume.toFixed(0)}</td>
                                    <td>${w.start_base.toFixed(3)}</td>
                                    <td>${w.end_base.toFixed(3)}</td>
                                    <td class="${baseDeltaClass}">${w.base_delta >= 0 ? '+' : ''}${w.base_delta.toFixed(3)}</td>
                                    <td>$${w.start_quote.toFixed(0)}</td>
                                    <td>$${w.end_quote.toFixed(0)}</td>
                                    <td class="${quoteDeltaClass}">${w.quote_delta >= 0 ? '+' : ''}$${w.quote_delta.toFixed(0)}</td>
                                    <td class="${tradingPnlClass}">${w.realized_pnl >= 0 ? '+' : ''}$${w.realized_pnl.toFixed(2)}</td>
                                    <td class="${marketPnlClass}">${w.unrealized_pnl >= 0 ? '+' : ''}$${w.unrealized_pnl.toFixed(2)}</td>
                                    <td class="${totalPnlClass}">${w.total_pnl >= 0 ? '+' : ''}$${w.total_pnl.toFixed(2)}</td>
                                    <td class="${tradingPnlClass}">$${w.pnl_per_hour.toFixed(2)}</td>
                                </tr>
                            `;
                        }
                        document.getElementById('windows-body').innerHTML = windowsHtml || '<tr><td colspan="15">No data yet</td></tr>';
    
                        // Update parameters
                        let paramsHtml = '';
                        for (const p of data.parameters) {
                            const pnlClass = p.net_pnl > 0 ? 'positive' : p.net_pnl < 0 ? 'negative' : '';
                            const isCurrent = p.id === (s ? s.parameter_set_id : null);
                            paramsHtml += `
                                <tr ${isCurrent ? 'class="highlight-current"' : ''}>
                                    <td>${p.id}${isCurrent ? ' ⭐' : ''}</td>
                                    <td>${p.spread_bps} bps</td>
                                    <td>${p.order_size}</td>
                                    <td>${p.skew}</td>
                                    <td>${p.hours.toFixed(1)}h</td>
                                    <td>${p.fills}</td>
                                    <td class="${pnlClass}">$${p.net_pnl.toFixed(2)}</td>
                                    <td class="${pnlClass}">$${p.pnl_per_hour.toFixed(2)}</td>
                                </tr>
                            `;
                        }
                        document.getElementById('params-body').innerHTML = paramsHtml || '<tr><td colspan="8">No configs yet</td></tr>';
    
                        // Update parameter changes timeline
                        const changesContainer = document.getElementById('param-changes-container');
                        if (data.parameter_changes && data.parameter_changes.length > 0) {
                            let changesHtml = '';
                            for (const change of data.parameter_changes) {
                                const timestamp = new Date(change.timestamp).toLocaleString();
                                const reasonBadge = change.reason || 'manual';
    
                                changesHtml += `
                                    <div class="timeline-item">
                                        <div class="timeline-header">
                                            <span class="timeline-timestamp">${timestamp}</span>
                                            <span class="timeline-reason">${reasonBadge}</span>
                                        </div>
                                        ${change.change_summary ? `<div style="color: #e0e0e0; margin-bottom: 8px;">${change.change_summary}</div>` : ''}
                                        <div class="timeline-change">
                                            <div class="timeline-old">
                                                Config #${change.old_param_id || 'N/A'}
                                                ${change.old_spread ? `(${change.old_spread} bps)` : ''}
                                            </div>
                                            <div class="timeline-arrow">→</div>
                                            <div class="timeline-new">
                                                Config #${change.new_param_id}
                                                ${change.new_spread ? `(${change.new_spread} bps)` : ''}
                                            </div>
                                        </div>
                                        ${change.notes ? `<div style="color: #888; font-size: 12px; margin-top: 8px; font-style: italic;">${change.notes}</div>` : ''}
                                    </div>
                                `;
                            }
                            changesContainer.innerHTML = changesHtml;
                        } else {
                            changesContainer.innerHTML = '<p style="color: #888;">No configuration changes recorded yet</p>';
                        }
                    })
                    .catch(err => console.error('Fetch error:', err));
            }
    
            // Position Chart
            let positionChart = null;
            let selectedChartWindow = 4;  // Default to 4H
    
            function selectChartWindow(window) {
                selectedChartWindow = window;
    
                // Update button states
                document.querySelectorAll('.chart-window-btn').forEach(btn => {
                    btn.classList.remove('active');
                });
                document.querySelector(`[data-chart-window="${window}"]`).classList.add('active');
    
                // Update chart
                updatePositionChart();
            }
    
            function updatePositionChart() {
                fetch('api/position_chart?window=' + encodeURIComponent(selectedChartWindow))
                    .then(r => r.json())
                    .then(data => {
                        if (!data.success) {
                            console.error('Chart error:', data.error);
                            document.getElementById('chart-insights').innerHTML =
                                '<div class="chart-insight-item">⚠️ No data available for this time window</div>';
                            return;
                        }
    
                        const chartData = data.chart_data;
    
                        // Update insights
                        const insightsHtml = chartData.insights.map(insight =>
                            `<div class="chart-insight-item">${insight}</div>`
                        ).join('');
                        document.getElementById('chart-insights').innerHTML = insightsHtml;
    
                        // Render chart
                        renderPositionChart(chartData);
                    })
                    .catch(err => {
                        console.error('Chart fetch error:', err);
                        document.getElementById('chart-insights').innerHTML =
                            '<div class="chart-insight-item">⚠️ Error loading chart data</div>';
                    });
            }
    
            function renderPositionChart(chartData) {
                const ctx = document.getElementById('position-chart').getContext('2d');
    
                // Destroy existing chart
                if (positionChart) {
                    positionChart.destroy();
                }
    
                // Format timestamps for display
                const labels = chartData.timestamps.map(ts => {
                    const date = new Date(ts);
                    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
                });
    
                positionChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: 'Price (USD)',
                                data: chartData.prices,
                                borderColor: '#00ccff',
                                backgroundColor: 'rgba(0, 204, 255, 0.1)',
                                borderWidth: 2,
                                yAxisID: 'y-price',
                                pointRadius: 2,
                                pointHoverRadius: 5,
                                tension: 0.1
                            },
                            {
                                label: 'Position (XMR)',
                                data: chartData.positions,
                                borderColor: '#00ff88',
                                backgroundColor: 'rgba(0, 255, 136, 0.2)',
                                borderWidth: 2,
                                yAxisID: 'y-position',
                                pointRadius: 2,
                                pointHoverRadius: 5,
                                tension: 0.1,
                                fill: true
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {
                            mode: 'index',
                            intersect: false
                        },
                        plugins: {
                            legend: {
                                display: true,
                                position: 'top',
                                labels: {
                                    color: '#e0e0e0',
                                    font: {
                                        family: "'SF Mono', 'Monaco', 'Courier New', monospace",
                                        size: 12
                                    }
                                }
                            },
                            tooltip: {
                                backgroundColor: '#1a2140',
                                titleColor: '#00ccff',
                                bodyColor: '#e0e0e0',
                                borderColor: '#00ccff',
                                borderWidth: 1,
                                padding: 12,
                                displayColors: true,
                                callbacks: {
                                    label: function(context) {
                                        let label = context.dataset.label || '';
                                        if (label) {
                                            label += ': ';
                                        }
                                        if (context.parsed.y !== null) {
                                            if (context.datasetIndex === 0) {
                                                label += '$' + context.parsed.y.toFixed(2);
                                            } else {
                                                label += context.parsed.y.toFixed(3) + ' {{ base_token }}';
                                            }
                                        }
                                        return label;
                                    }
                                }
                            }
                        },
                        scales: {
                            x: {
                                grid: {
                                    color: '#2a3359',
                                    borderColor: '#00ccff'
                                },
                                ticks: {
                                    color: '#888',
                                    font: {
                                        family: "'SF Mono', 'Monaco', 'Courier New', monospace",
                                        size: 10
                                    },
                                    maxRotation: 45,
                                    minRotation: 45
                                }
                            },
                            'y-price': {
                                type: 'linear',
                                position: 'left',
                                grid: {
                                    color: '#2a3359',
                                    borderColor: '#00ccff'
                                },
                                ticks: {
                                    color: '#00ccff',
                                    font: {
                                        family: "'SF Mono', 'Monaco', 'Courier New', monospace",
                                        size: 11
                                    },
                                    callback: function(value) {
                                        return '$' + value.toFixed(2);
                                    }
                                },
                                title: {
                                    display: true,
                                    text: 'Price (USD)',
                                    color: '#00ccff',
                                    font: {
                                        family: "'SF Mono', 'Monaco', 'Courier New', monospace",
                                        size: 12,
                                        weight: 'bold'
                                    }
                                }
                            },
                            'y-position': {
                                type: 'linear',
                                position: 'right',
                                grid: {
                                    display: false
                                },
                                ticks: {
                                    color: '#00ff88',
                                    font: {
                                        family: "'SF Mono', 'Monaco', 'Courier New', monospace",
                                        size: 11
                                    },
                                    callback: function(value) {
                                        return value.toFixed(3) + ' {{ base_token }}';
                                    }
                                },
                                title: {
                                    display: true,
                                    text: 'Position (XMR)',
                                    color: '#00ff88',
                                    font: {
                                        family: "'SF Mono', 'Monaco', 'Courier New', monospace",
                                        size: 12,
                                        weight: 'bold'
                                    }
                                }
                            }
                        }
                    }
                });
            }
    
            // Update immediately and every 60 seconds
            updateDashboard();
            updatePositionChart();  // Load chart initially
            setInterval(updateDashboard, 60000);
            setInterval(updatePositionChart, 60000);  // Refresh chart every minute
        </script>
    </body>
    </html>
    """
    

    return bp
