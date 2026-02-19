#!/usr/bin/env python3
"""
Perpetual Market Making Dashboard Blueprint - V2
Matches spot dashboard features with perp-specific metrics

Features:
- Time Window Selector (1H, 4H, 8H, 24H, ALL)
- Static vs Rolling mode
- Position & Price Chart
- Configuration Changes Timeline
- 8 Summary Cards with detailed metrics
- Strategy Analysis (Alpha, Buy & Hold comparison)
- Toxicity/Markout Analysis
- Funding Rate Tracking
- Margin Ratio Monitoring
"""

from flask import Blueprint, render_template_string, jsonify, request
from datetime import datetime, timedelta, timezone
import sqlite3
import json
import os
import sys

# Add lib to path for bot_manager import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from bot_manager import get_bot_manager

# Default database path (can be overridden when creating blueprint)
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trading_data.db")

def create_perp_dashboard_blueprint(market_name, route_prefix, database_path=None, config_file=None, is_grid=False):
    """
    Create a dashboard blueprint for a perpetual market

    Args:
        market_name: Market name like "ICP", "HYPE", "ETH", or "xyz:GOLD" for grid bots
        route_prefix: URL prefix like "icp-perp", "hype-perp", "gold-grid"
        database_path: Optional path to database
        config_file: Optional config filename for bot control
        is_grid: If True, this is a grid bot (market_name may have dex prefix like "xyz:GOLD")

    Returns:
        Flask Blueprint
    """
    bp = Blueprint(f'dashboard_{route_prefix}', __name__, url_prefix=f'/{route_prefix}')

    # This market's name for display
    # For grid bots with dex prefix (e.g., "xyz:GOLD"), extract clean name for display
    if is_grid and ':' in market_name:
        MARKET_DISPLAY = market_name.split(':')[-1]
    else:
        MARKET_DISPLAY = market_name

    # Database query market name - both perp and grid bots store with "-PERP" suffix
    # Grid bots: "xyz:GOLD-PERP", Perp bots: "BTC-PERP"
    MARKET = f"{market_name}-PERP"

    # API market name - for querying positions/orders from Hyperliquid
    # Hyperliquid API uses raw market name without "-PERP" suffix
    # Grid bots: "xyz:GOLD", Perp bots: "BTC"
    MARKET_API = market_name
    DB_PATH = database_path or DATABASE_PATH
    CONFIG_FILE = config_file  # For bot control

    def get_db():
        """Get database connection"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def calculate_toxicity_metrics(start_time_str, end_time_str=None):
        """Calculate toxicity/adverse selection metrics for a time window"""
        conn = get_db()
        cursor = conn.cursor()

        if end_time_str:
            cursor.execute("""
                SELECT timestamp, price, side, base_amount
                FROM fills
                WHERE pair = ? AND timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
            """, (MARKET, start_time_str, end_time_str))
        else:
            cursor.execute("""
                SELECT timestamp, price, side, base_amount
                FROM fills
                WHERE pair = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (MARKET, start_time_str))

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

        trades = []
        for fill in fills:
            trades.append({
                'time': datetime.fromisoformat(fill['timestamp'].replace('+00:00', '').replace('Z', '')),
                'price': float(fill['price']),
                'side': fill['side'],
                'size': float(fill['base_amount'])
            })

        markouts_5s = []
        markouts_30s = []
        negative_30s_count = 0

        for i, trade in enumerate(trades):
            fill_price = trade['price']
            fill_time = trade['time']
            side = trade['side']

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

            if future_prices_5s:
                mid_5s = sum(future_prices_5s) / len(future_prices_5s)
                if side == 'buy':
                    markout = mid_5s - fill_price
                else:
                    markout = fill_price - mid_5s
                markouts_5s.append((markout / fill_price) * 10000)

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

        buys = [t for t in trades if t['side'] == 'buy']
        sells = [t for t in trades if t['side'] == 'sell']
        buy_pct = len(buys) / len(trades) * 100 if trades else 50
        sell_pct = len(sells) / len(trades) * 100 if trades else 50
        imbalance_score = abs(buy_pct - 50) * 2

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
        """, (MARKET,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        # Check if the status is stale (older than 2 minutes)
        try:
            from dateutil import parser
            last_update = parser.parse(row['timestamp'])
            now = datetime.now(timezone.utc)
            age_seconds = (now - last_update).total_seconds()
            is_stale = age_seconds > 120  # 2 minutes
        except:
            is_stale = True  # If we can't parse, assume stale

        # If status is stale, bot is not live
        if is_stale:
            bid_live = False
            ask_live = False
        else:
            bid_live = bool(row['bid_live']) if row['bid_live'] is not None else False
            ask_live = bool(row['ask_live']) if row['ask_live'] is not None else False

        return {
            'timestamp': row['timestamp'],
            'base_balance': row['base_balance'],
            'quote_balance': row['quote_balance'],
            'base_total': row['base_total'],
            'quote_total': row['quote_total'],
            'mid_price': row['mid_price'],
            'total_value_usd': row['total_value_usd'],
            'bid_live': bid_live,
            'ask_live': ask_live,
            'our_bid_price': row['our_bid_price'],
            'our_ask_price': row['our_ask_price'],
            'parameter_set_id': row['parameter_set_id'],
            'is_stale': is_stale
        }

    def get_window_stats(start_time_str, end_time_str=None):
        """Get statistics for a time window - works with fills only if no metrics_1min"""
        conn = get_db()
        cursor = conn.cursor()

        # First check if we have metrics_1min data
        has_metrics = False
        start_row = None
        end_row = None
        agg_row = None
        actual_start = start_time_str

        # Try to get metrics_1min data
        cursor.execute("""
            SELECT base_total, quote_total, mid_price, total_value_usd, timestamp
            FROM metrics_1min
            WHERE pair = ? AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT 1
        """, (MARKET, start_time_str))
        start_row = cursor.fetchone()

        if start_row:
            has_metrics = True
            actual_start = start_row['timestamp']

            # Get end snapshot
            if end_time_str:
                cursor.execute("""
                    SELECT base_total, quote_total, mid_price, total_value_usd
                    FROM metrics_1min
                    WHERE pair = ? AND timestamp >= ? AND timestamp < ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (MARKET, actual_start, end_time_str))
            else:
                cursor.execute("""
                    SELECT base_total, quote_total, mid_price, total_value_usd
                    FROM metrics_1min
                    WHERE pair = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (MARKET, actual_start))
            end_row = cursor.fetchone()

            # Get aggregates
            if end_time_str:
                cursor.execute("""
                    SELECT
                        COUNT(*) as minutes,
                        SUM(CASE WHEN bid_live AND ask_live THEN 1 ELSE 0 END) as both_live_minutes
                    FROM metrics_1min
                    WHERE pair = ? AND timestamp >= ? AND timestamp < ?
                """, (MARKET, actual_start, end_time_str))
            else:
                cursor.execute("""
                    SELECT
                        COUNT(*) as minutes,
                        SUM(CASE WHEN bid_live AND ask_live THEN 1 ELSE 0 END) as both_live_minutes
                    FROM metrics_1min
                    WHERE pair = ? AND timestamp >= ?
                """, (MARKET, actual_start))
            agg_row = cursor.fetchone()

        # Get fills data - this works even without metrics_1min
        if end_time_str:
            cursor.execute("""
                SELECT
                    COUNT(*) as fills_count,
                    SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buy_fills,
                    SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sell_fills,
                    COALESCE(SUM(quote_amount), 0) as volume_quote,
                    COALESCE(SUM(fee), 0) as fees_paid,
                    COALESCE(SUM(realized_pnl), 0) as realized_pnl,
                    MIN(timestamp) as first_fill,
                    MAX(timestamp) as last_fill
                FROM fills
                WHERE pair = ? AND timestamp >= ? AND timestamp < ?
            """, (MARKET, start_time_str, end_time_str))
        else:
            cursor.execute("""
                SELECT
                    COUNT(*) as fills_count,
                    SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buy_fills,
                    SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sell_fills,
                    COALESCE(SUM(quote_amount), 0) as volume_quote,
                    COALESCE(SUM(fee), 0) as fees_paid,
                    COALESCE(SUM(realized_pnl), 0) as realized_pnl,
                    MIN(timestamp) as first_fill,
                    MAX(timestamp) as last_fill
                FROM fills
                WHERE pair = ? AND timestamp >= ?
            """, (MARKET, start_time_str))

        fills_row = cursor.fetchone()

        # Get funding payments for this window (table may not exist)
        try:
            if end_time_str:
                cursor.execute("""
                    SELECT COALESCE(SUM(payment_usd), 0) as total_funding
                    FROM funding_payments
                    WHERE market = ? AND timestamp >= ? AND timestamp < ?
                """, (MARKET, start_time_str, end_time_str))
            else:
                cursor.execute("""
                    SELECT COALESCE(SUM(payment_usd), 0) as total_funding
                    FROM funding_payments
                    WHERE market = ? AND timestamp >= ?
                """, (MARKET, start_time_str))
            funding_row = cursor.fetchone()
        except sqlite3.OperationalError:
            funding_row = None
        conn.close()

        fills_count = fills_row['fills_count'] or 0 if fills_row else 0

        # If no metrics and no fills, return None
        if not has_metrics and fills_count == 0:
            return None

        # Calculate values based on what data we have
        if has_metrics and start_row and end_row and agg_row and agg_row['minutes'] > 0:
            # Full metrics mode
            start_base = float(start_row['base_total'] or 0)
            start_quote = float(start_row['quote_total'] or 0)
            start_price = float(start_row['mid_price'] or 0)
            start_value = float(start_row['total_value_usd'] or 0)

            end_base = float(end_row['base_total'] or 0)
            end_quote = float(end_row['quote_total'] or 0)
            end_price = float(end_row['mid_price'] or 0)
            end_value = float(end_row['total_value_usd'] or 0)

            # PnL calculations - FOR PERPS, use realized PnL from fills, not base*price math
            # The spot formula (base*price + quote) doesn't work for perpetuals
            trading_pnl = float(fills_row['realized_pnl'] or 0) if fills_row else 0

            # Market PnL for perps = position × price change
            # This measures unrealized P&L from holding the current position
            # Using end_base since that's the position we're currently holding
            start_total_value = start_value
            end_total_value = end_value
            price_change = end_price - start_price
            market_pnl = end_base * price_change  # Positive position + price up = profit
            total_pnl = trading_pnl + market_pnl
            base_delta = end_base - start_base
            quote_delta = end_quote - start_quote
            uptime_pct = (agg_row['both_live_minutes'] / agg_row['minutes'] * 100) if agg_row['minutes'] > 0 else 0
            hours = agg_row['minutes'] / 60.0
        else:
            # Fills-only mode - estimate duration from fills
            trading_pnl = float(fills_row['realized_pnl'] or 0) if fills_row else 0
            market_pnl = 0  # Can't calculate without metrics
            total_pnl = trading_pnl
            base_delta = 0
            quote_delta = 0
            uptime_pct = None  # Unknown without metrics

            # Calculate hours from fills timespan
            if fills_row and fills_row['first_fill'] and fills_row['last_fill']:
                try:
                    from dateutil import parser
                    first = parser.parse(fills_row['first_fill'])
                    last = parser.parse(fills_row['last_fill'])
                    hours = (last - first).total_seconds() / 3600.0
                    if hours < 0.1:
                        hours = 1.0  # Minimum 1 hour for rate calculations
                except:
                    hours = 1.0
            else:
                hours = 1.0

        buy_fills = fills_row['buy_fills'] or 0 if fills_row else 0
        sell_fills = fills_row['sell_fills'] or 0 if fills_row else 0
        volume_quote = float(fills_row['volume_quote'] or 0) if fills_row else 0
        fees_paid = float(fills_row['fees_paid'] or 0) if fills_row else 0
        realized_pnl_from_fills = float(fills_row['realized_pnl'] or 0) if fills_row else 0
        total_funding = float(funding_row['total_funding'] or 0) if funding_row else 0

        pnl_per_hour = trading_pnl / hours if hours > 0 else 0

        # Toxicity metrics
        toxicity = calculate_toxicity_metrics(start_time_str, end_time_str)

        # Build response - handle fills-only mode
        if has_metrics and agg_row:
            minutes = agg_row['minutes']
            start_price_val = float(start_row['mid_price'] or 0) if start_row else 0
            end_price_val = float(end_row['mid_price'] or 0) if end_row else 0
            avg_price = (start_price_val + end_price_val) / 2 if start_price_val and end_price_val else end_price_val
            start_value_val = start_total_value if 'start_total_value' in dir() else 0
            end_value_val = end_total_value if 'end_total_value' in dir() else 0
        else:
            minutes = int(hours * 60)
            avg_price = 0
            start_value_val = 0
            end_value_val = 0
            # Set defaults for fills-only mode
            start_base = 0
            start_quote = 0
            start_price = 0
            end_base = 0
            end_quote = 0
            end_price = 0
            start_total_value = 0
            end_total_value = 0

        return {
            'minutes': minutes,
            'hours': hours,
            'fills': fills_count,
            'buy_fills': buy_fills,
            'sell_fills': sell_fills,
            'volume': volume_quote,
            'realized_pnl': trading_pnl,
            'unrealized_pnl': market_pnl,
            'total_pnl': total_pnl,
            'fees': fees_paid,
            'funding': total_funding,
            'pnl_per_hour': pnl_per_hour,
            'avg_price': avg_price,
            'uptime_pct': uptime_pct,
            'start_base': start_base if has_metrics else 0,
            'start_quote': start_quote if has_metrics else 0,
            'start_price': start_price if has_metrics else 0,
            'start_value': start_total_value if has_metrics else 0,
            'end_base': end_base if has_metrics else 0,
            'end_quote': end_quote if has_metrics else 0,
            'end_price': end_price if has_metrics else 0,
            'end_value': end_total_value if has_metrics else 0,
            'base_delta': base_delta,
            'quote_delta': quote_delta,
            'toxicity': toxicity
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
        """, (MARKET,))

        rows = cursor.fetchall()
        conn.close()

        results = []
        for row in rows:
            hours = row['minutes_run'] / 60.0 if row['minutes_run'] else 0
            pnl_per_hour = row['total_net_pnl'] / hours if hours > 0 and row['total_net_pnl'] else 0

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

        cursor.execute("""
            SELECT MAX(total_value_usd) as peak_value
            FROM metrics_1min
            WHERE pair = ? AND total_value_usd IS NOT NULL
        """, (MARKET,))

        peak_row = cursor.fetchone()
        peak_value = peak_row['peak_value'] if peak_row else None

        cursor.execute("""
            SELECT total_value_usd
            FROM metrics_1min
            WHERE pair = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (MARKET,))

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
            """, (MARKET, start_time_str, end_time_str))
        else:
            cursor.execute("""
                SELECT timestamp, mid_price, base_total
                FROM metrics_1min
                WHERE pair = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (MARKET, start_time_str))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return None

        timestamps = []
        prices = []
        positions = []

        for row in rows:
            timestamps.append(row['timestamp'])
            prices.append(float(row['mid_price']) if row['mid_price'] else None)
            positions.append(float(row['base_total']) if row['base_total'] else None)

        correlation = calculate_correlation(prices, positions)
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

        valid_pairs = [(p, pos) for p, pos in zip(prices, positions) if p is not None and pos is not None]
        if len(valid_pairs) < 2:
            return 0.0

        prices_clean = [p for p, _ in valid_pairs]
        positions_clean = [pos for _, pos in valid_pairs]

        price_mean = sum(prices_clean) / len(prices_clean)
        pos_mean = sum(positions_clean) / len(positions_clean)

        numerator = sum((p - price_mean) * (pos - pos_mean) for p, pos in zip(prices_clean, positions_clean))
        price_std = sum((p - price_mean) ** 2 for p in prices_clean) ** 0.5
        pos_std = sum((pos - pos_mean) ** 2 for pos in positions_clean) ** 0.5

        if price_std == 0 or pos_std == 0:
            return 0.0

        return numerator / (price_std * pos_std)

    def generate_position_insights(timestamps, prices, positions, correlation):
        """Generate insights about position and price relationship"""
        insights = []

        if correlation > 0.5:
            insights.append(f"Strong positive correlation (+{correlation:.2f}) - accumulating during price increases")
        elif correlation > 0.2:
            insights.append(f"Slight positive correlation (+{correlation:.2f}) - decent position timing")
        elif correlation > -0.2:
            insights.append(f"Low correlation ({correlation:+.2f}) - position changes independent of price")
        elif correlation > -0.5:
            insights.append(f"Negative correlation ({correlation:+.2f}) - accumulating during price drops")
        else:
            insights.append(f"Strong negative correlation ({correlation:+.2f}) - poor position timing!")

        valid_positions = [pos for pos in positions if pos is not None]
        if valid_positions:
            max_pos = max(valid_positions)
            min_pos = min(valid_positions)
            avg_pos = sum(valid_positions) / len(valid_positions)

            # Check for long vs short bias
            if avg_pos > 0:
                insights.append(f"Average position: +{avg_pos:.2f} {MARKET_DISPLAY} (long bias)")
            elif avg_pos < 0:
                insights.append(f"Average position: {avg_pos:.2f} {MARKET_DISPLAY} (short bias)")
            else:
                insights.append(f"Average position: neutral")

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
        """, (MARKET,))

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

    def get_live_position():
        """Get current position from Hyperliquid API"""
        try:
            vibetraders_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            import sys
            sys.path.insert(0, os.path.join(vibetraders_root, 'lib'))

            from config_discovery import ConfigDiscovery
            discovery = ConfigDiscovery(config_dir=os.path.join(vibetraders_root, 'config'))
            pair_info = discovery.get_pair_info(route_prefix)

            if not pair_info:
                return None

            from credentials import get_credentials

            if pair_info.get('is_subaccount'):
                account_address = pair_info['subaccount_address']
            else:
                account_address = get_credentials()['account_address']

            from hyperliquid.info import Info
            from hyperliquid.utils import constants

            # HIP-3 markets (like xyz:GOLD) need perp_dexs parameter
            if ':' in MARKET_API:
                dex = MARKET_API.split(':')[0]
                info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=["", dex])
            else:
                info = Info(constants.MAINNET_API_URL, skip_ws=True)
            user_state = info.user_state(account_address)

            asset_positions = user_state.get('assetPositions', [])
            perp_position = next(
                (p for p in asset_positions if p['position']['coin'] == MARKET_API),
                None
            )

            if perp_position:
                pos_data = perp_position['position']
                position = {
                    'size': float(pos_data.get('szi', 0.0)),
                    'entry_px': float(pos_data.get('entryPx', 0.0)),
                    'position_value': float(pos_data.get('positionValue', 0.0)),
                    'unrealized_pnl': float(pos_data.get('unrealizedPnl', 0.0)),
                    'leverage_str': pos_data.get('leverage', {}).get('value', '0'),
                    'liquidation_px': pos_data.get('liquidationPx')
                }
            else:
                position = {
                    'size': 0.0,
                    'entry_px': 0.0,
                    'position_value': 0.0,
                    'unrealized_pnl': 0.0,
                    'leverage_str': '0',
                    'liquidation_px': None
                }

            margin_summary = user_state.get('marginSummary', {})
            margin = {
                'account_value': float(margin_summary.get('accountValue', 0.0)),
                'total_margin_used': float(margin_summary.get('totalMarginUsed', 0.0)),
                'total_ntl_pos': float(margin_summary.get('totalNtlPos', 0.0))
            }

            if margin['total_margin_used'] > 0:
                margin['margin_ratio_pct'] = (margin['account_value'] / margin['total_margin_used']) * 100
            else:
                # No position = no margin used = no liquidation risk, return None to skip alert
                margin['margin_ratio_pct'] = None

            meta = info.meta()
            universe = meta.get('universe', [])
            market_info = next((m for m in universe if m['name'] == MARKET_API), None)

            funding_rate = 0.0
            if market_info:
                funding_str = market_info.get('funding', '0.0')
                funding_rate = float(funding_str)

            return {
                'position': position,
                'margin': margin,
                'funding_rate_8h': funding_rate
            }
        except Exception as e:
            print(f"Error getting live position: {e}")
            return None

    # ============================================================================
    # API ROUTES
    # ============================================================================

    @bp.route('/')
    def index():
        return render_template_string(DASHBOARD_HTML, market_name=MARKET_DISPLAY, route_prefix=route_prefix, config_file=CONFIG_FILE)

    @bp.route('/api/data')
    def get_data():
        """Get all dashboard data"""
        try:
            now = datetime.now(timezone.utc)

            window_mode = request.args.get('mode', 'static')
            windows_hours = request.args.get('windows', '1,4,8,24')

            window_list = []
            for h in windows_hours.split(','):
                h = h.strip().lower()
                if h == 'all':
                    window_list.append('all')
                elif h:
                    try:
                        window_list.append(float(h))
                    except ValueError:
                        continue

            status = get_current_status()

            windows = {}
            window_labels = []
            window_ranges = {}

            for hours in window_list:
                if hours == 'all':
                    conn = get_db()
                    cursor = conn.cursor()
                    # Get earliest time from BOTH metrics_1min and fills
                    cursor.execute("""
                        SELECT MIN(timestamp) as first_time
                        FROM metrics_1min
                        WHERE pair = ?
                    """, (MARKET,))
                    metrics_first = cursor.fetchone()
                    metrics_time = metrics_first['first_time'] if metrics_first else None

                    cursor.execute("""
                        SELECT MIN(timestamp) as first_time
                        FROM fills
                        WHERE pair = ?
                    """, (MARKET,))
                    fills_first = cursor.fetchone()
                    fills_time = fills_first['first_time'] if fills_first else None

                    conn.close()

                    # Use the earliest timestamp from either table
                    if metrics_time and fills_time:
                        start_time_str = min(metrics_time, fills_time)
                    elif metrics_time:
                        start_time_str = metrics_time
                    elif fills_time:
                        start_time_str = fills_time
                    else:
                        start_time_str = None

                    if start_time_str:
                        stats = get_window_stats(start_time_str)
                        label = 'ALL'
                        window_ranges[label] = {'start': start_time_str, 'end': 'now'}
                    else:
                        stats = None
                        label = 'ALL'
                        window_ranges[label] = {'start': 'N/A', 'end': 'N/A'}
                else:
                    if window_mode == 'rolling':
                        start_time = now - timedelta(hours=hours)
                    else:
                        if hours == 24:
                            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        elif hours == 1:
                            start_time = now.replace(minute=0, second=0, microsecond=0)
                        else:
                            hours_since_midnight = now.hour
                            boundary_hour = (hours_since_midnight // int(hours)) * int(hours)
                            start_time = now.replace(hour=boundary_hour, minute=0, second=0, microsecond=0)

                    start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S+00:00')
                    stats = get_window_stats(start_time_str)

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

                windows[label] = stats
                window_labels.append(label)

            param_comparison = get_parameter_comparison()
            param_changes = get_parameter_changes()
            drawdown = get_drawdown()
            live_position = get_live_position()

            return jsonify({
                'success': True,
                'status': status,
                'windows': windows,
                'window_labels': window_labels,
                'window_ranges': window_ranges,
                'parameters': param_comparison,
                'parameter_changes': param_changes,
                'drawdown': drawdown,
                'live_position': live_position,
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
            now = datetime.now(timezone.utc)
            window = request.args.get('window', '4').lower()

            if window == 'all':
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MIN(timestamp) as first_time
                    FROM metrics_1min
                    WHERE pair = ?
                """, (MARKET,))
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

    @bp.route('/api/fills')
    def api_fills():
        """Get recent fills"""
        limit = request.args.get('limit', 50, type=int)
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, side, price, base_amount, quote_amount, fee, realized_pnl, spread_bps
            FROM fills
            WHERE pair = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (MARKET, limit))

        fills = []
        for row in cursor.fetchall():
            fills.append({
                'timestamp': row['timestamp'],
                'side': row['side'],
                'price': float(row['price']),
                'size': float(row['base_amount']),
                'value': float(row['quote_amount']),
                'fee': float(row['fee']) if row['fee'] else 0,
                'pnl': float(row['realized_pnl']) if row['realized_pnl'] else 0,
                'spread_bps': float(row['spread_bps']) if row['spread_bps'] else 0
            })

        conn.close()
        return jsonify({'fills': fills})

    @bp.route('/api/clear_data', methods=['POST'])
    def clear_data():
        """Clear all metrics and fills data for this market only"""
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Count records before deletion
            cursor.execute("SELECT COUNT(*) FROM metrics_1min WHERE pair = ?", (MARKET,))
            metrics_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM fills WHERE pair = ?", (MARKET,))
            fills_count = cursor.fetchone()[0]

            # Delete data for this market only
            cursor.execute("DELETE FROM metrics_1min WHERE pair = ?", (MARKET,))
            cursor.execute("DELETE FROM fills WHERE pair = ?", (MARKET,))

            # Also try to clear funding_payments if table exists
            try:
                cursor.execute("DELETE FROM funding_payments WHERE market = ?", (MARKET,))
            except:
                pass  # Table might not exist

            conn.commit()
            conn.close()

            return jsonify({
                'success': True,
                'message': f'Cleared data for {MARKET}',
                'deleted': {
                    'metrics': metrics_count,
                    'fills': fills_count
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    # ============================================================================
    # DASHBOARD HTML TEMPLATE
    # ============================================================================

    DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>{{ market_name }}-PERP Dashboard</title>
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
        .badge-perp { background: #667eea; color: #fff; }
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
        .alert-warning {
            border-left-color: #ffaa00;
        }
        .alert-info {
            border-left-color: #00ccff;
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
            color: #888;
            font-size: 12px;
        }
        .timeline-reason {
            background: #00ccff;
            color: #000;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .timeline-change {
            display: flex;
            align-items: center;
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
        .back-link {
            display: inline-block;
            color: #00ccff;
            text-decoration: none;
            margin-bottom: 15px;
            font-size: 13px;
        }
        .back-link:hover {
            text-decoration: underline;
        }
        @media (max-width: 1200px) {
            .summary-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        @media (max-width: 768px) {
            .summary-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Bot Controls */
        .bot-control-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: #1a1f3a;
            border: 1px solid #2a2f4a;
            border-radius: 8px;
            padding: 12px 20px;
            margin-bottom: 20px;
        }
        .bot-control-left {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .bot-status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #6b7280;
        }
        .status-dot.running {
            background: #10b981;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .status-text {
            font-size: 14px;
            color: #8b92b0;
        }
        .status-text.running { color: #10b981; }
        .bot-control-btn {
            padding: 8px 20px;
            border: none;
            border-radius: 6px;
            font-family: inherit;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-start {
            background: #10b981;
            color: white;
        }
        .btn-start:hover { background: #059669; }
        .btn-start:disabled {
            background: #374151;
            cursor: not-allowed;
        }
        .btn-stop {
            background: #f59e0b;
            color: white;
        }
        .btn-stop:hover { background: #d97706; }
        .btn-stop-all {
            background: #ef4444;
            color: white;
        }
        .btn-stop-all:hover { background: #dc2626; }
        .btn-clear-data {
            background: #6b7280;
            color: white;
        }
        .btn-clear-data:hover { background: #4b5563; }
        .bot-uptime {
            font-size: 12px;
            color: #6b7280;
        }
        .control-right {
            display: flex;
            gap: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <a href="/" class="back-link">← Back to Portfolio</a>
            <a href="/ai" style="color: #8b5cf6; text-decoration: none; font-size: 18px;" title="AI Settings">⚙️</a>
        </div>

        <!-- Bot Control Bar -->
        {% if config_file %}
        <div class="bot-control-bar">
            <div class="bot-control-left">
                <div class="bot-status-indicator">
                    <div class="status-dot" id="botStatusDot"></div>
                    <span class="status-text" id="botStatusText">Checking...</span>
                    <span class="bot-uptime" id="botUptime"></span>
                </div>
                <button class="bot-control-btn btn-start" id="btnStart" onclick="startBot()">Start Bot</button>
                <button class="bot-control-btn btn-stop" id="btnStop" onclick="stopBot()" style="display: none;">Stop Bot</button>
            </div>
            <div class="control-right">
                <button class="bot-control-btn btn-clear-data" onclick="clearData()">Clear Data</button>
                <button class="bot-control-btn btn-stop-all" onclick="stopAllBots()">Stop All Bots</button>
            </div>
        </div>
        {% else %}
        <div class="bot-control-bar">
            <div class="bot-control-left">
                <span class="status-text">No config file linked to this dashboard</span>
            </div>
            <div class="control-right">
                <button class="bot-control-btn btn-clear-data" onclick="clearData()">Clear Data</button>
                <button class="bot-control-btn btn-stop-all" onclick="stopAllBots()">Stop All Bots</button>
            </div>
        </div>
        {% endif %}

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <h1 style="margin: 0;">{{ market_name }}-PERP Dashboard <span class="badge-perp" style="font-size: 12px; vertical-align: middle;">PERPETUAL</span></h1>
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
                <div class="summary-row">
                    <span>Funding</span>
                    <span id="sum-funding">...</span>
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
                        <span class="tooltiptext">What you'd have made going 1x long at the start of this window</span>
                    </span>
                    <span id="sum-buyhold">...</span>
                </div>
                <div class="summary-row">
                    <span class="tooltip">Alpha:
                        <span class="tooltiptext">How much better/worse you did vs passive long. Positive = you beat buy & hold!</span>
                    </span>
                    <span id="sum-alpha">...</span>
                </div>
                <div class="summary-row">
                    <span class="tooltip">Market Direction:
                        <span class="tooltiptext">Profit from position change × price movement</span>
                    </span>
                    <span id="sum-direction">...</span>
                </div>
                <div class="summary-row">
                    <span class="tooltip">Trading Skill:
                        <span class="tooltiptext">Pure spread capture profit independent of price moves</span>
                    </span>
                    <span id="sum-skill">...</span>
                </div>
            </div>

            <div class="summary-card">
                <h3>📍 Live Position</h3>
                <div class="summary-row">
                    <span>Position Size</span>
                    <span id="sum-position-size">...</span>
                </div>
                <div class="summary-row">
                    <span>Entry Price</span>
                    <span id="sum-entry-price">...</span>
                </div>
                <div class="summary-row">
                    <span>Unrealized PnL</span>
                    <span id="sum-unrealized-pnl">...</span>
                </div>
                <div class="summary-row">
                    <span>Liquidation</span>
                    <span id="sum-liquidation">...</span>
                </div>
            </div>

            <div class="summary-card">
                <h3>💵 Funding Rate</h3>
                <div class="summary-row">
                    <span>Current 8H Rate</span>
                    <span id="sum-funding-rate">...</span>
                </div>
                <div class="summary-row">
                    <span>Annualized</span>
                    <span id="sum-funding-annual">...</span>
                </div>
                <div class="summary-row">
                    <span>Margin Ratio</span>
                    <span id="sum-margin-ratio">...</span>
                </div>
                <div class="summary-row">
                    <span>Account Value</span>
                    <span id="sum-account-value">...</span>
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
                    <span class="tooltip">Drawdown:
                        <span class="tooltiptext">Current decline from peak portfolio value</span>
                    </span>
                    <span id="sum-drawdown">...</span>
                </div>
            </div>

            <div class="summary-card">
                <h3>🛡️ Toxicity Monitor</h3>
                <div class="summary-row">
                    <span class="tooltip">Avg Markout 5s/30s:
                        <span class="tooltiptext">How price moves after fills. Positive = good, negative = toxic</span>
                    </span>
                    <span id="sum-markout">...</span>
                </div>
                <div class="summary-row">
                    <span class="tooltip">Negative Fills:
                        <span class="tooltiptext">% of fills where price moved against you within 30s</span>
                    </span>
                    <span id="sum-neg-fills">...</span>
                </div>
                <div class="summary-row">
                    <span class="tooltip">Buy/Sell Imbal:
                        <span class="tooltiptext">Are you getting hit mostly on one side?</span>
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
                    <span>Max Position:</span>
                    <span id="sum-max-pos">...</span>
                </div>
                <div class="summary-row">
                    <span>Duration:</span>
                    <span id="sum-duration">...</span>
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
                    <div class="stat-label">Mark Price</div>
                    <div class="stat-value" id="mid-price">...</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Our Spread</div>
                    <div class="stat-value" id="our-spread">...</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Position</div>
                    <div class="stat-value" id="current-position">...</div>
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

        <!-- Recent Fills -->
        <div class="section">
            <h2>📋 Recent Fills</h2>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Side</th>
                        <th>Price</th>
                        <th>Size</th>
                        <th>Value</th>
                        <th>Fee</th>
                        <th>PnL</th>
                    </tr>
                </thead>
                <tbody id="fills-body">
                    <tr><td colspan="7">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        let currentWindows = '1,4,8,24,all';
        let selectedWindow = 1;
        let windowMode = 'static';
        let cachedData = null;

        function setWindowMode(mode) {
            windowMode = mode;
            document.querySelectorAll('.mode-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            updateDashboard();
        }

        function selectWindow(windowHours) {
            selectedWindow = windowHours;
            document.querySelectorAll('.window-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelector(`[data-window="${windowHours}"]`).classList.add('active');
            updateSummaryCards();
        }

        function updateLivePositionCards(lp) {
            // Live Position card
            if (lp && lp.position) {
                const pos = lp.position;
                const posSize = pos.size;
                const posClass = posSize > 0 ? 'positive' : posSize < 0 ? 'negative' : 'neutral';
                const posLabel = posSize > 0 ? 'LONG' : posSize < 0 ? 'SHORT' : 'FLAT';

                document.getElementById('sum-position-size').innerHTML = `<span class="${posClass}">${Math.abs(posSize).toFixed(4)} ${posLabel}</span>`;
                document.getElementById('sum-entry-price').innerHTML = pos.entry_px > 0 ? '$' + pos.entry_px.toFixed(4) : 'N/A';
                document.getElementById('sum-unrealized-pnl').innerHTML = formatPnL(pos.unrealized_pnl);
                document.getElementById('sum-unrealized-pnl').className = getPnLClass(pos.unrealized_pnl);
                document.getElementById('sum-liquidation').innerHTML = pos.liquidation_px ? '$' + parseFloat(pos.liquidation_px).toFixed(2) : 'N/A';
            }

            // Funding Rate card
            if (lp) {
                const fundingRate8h = lp.funding_rate_8h * 100;
                const fundingAnnual = fundingRate8h * 3 * 365;
                const fundingClass = fundingRate8h >= 0 ? 'negative' : 'positive';

                document.getElementById('sum-funding-rate').innerHTML = `<span class="${fundingClass}">${fundingRate8h.toFixed(4)}%</span>`;
                document.getElementById('sum-funding-annual').innerHTML = `<span class="${fundingClass}">${fundingAnnual.toFixed(1)}%</span>`;

                if (lp.margin) {
                    const marginRatio = lp.margin.margin_ratio_pct;
                    if (marginRatio === null || marginRatio === undefined) {
                        // No position = no margin used = safe
                        document.getElementById('sum-margin-ratio').innerHTML = '<span class="neutral">No Position</span>';
                    } else {
                        const marginClass = marginRatio > 500 ? 'positive' : marginRatio > 200 ? 'warning' : 'negative';
                        document.getElementById('sum-margin-ratio').innerHTML = `<span class="${marginClass}">${marginRatio.toFixed(0)}%</span>`;
                    }
                    document.getElementById('sum-account-value').innerHTML = '$' + lp.margin.account_value.toFixed(2);
                }
            }
        }

        function updateSummaryCards() {
            if (!cachedData || !cachedData.windows) return;

            let windowLabel;
            if (selectedWindow === 'all') {
                windowLabel = 'ALL';
            } else {
                windowLabel = selectedWindow + 'h';
            }

            const w = cachedData.windows[windowLabel];
            const s = cachedData.status;
            const lp = cachedData.live_position;

            // Update window range indicator
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

            // Handle no data for this window
            if (!w) {
                document.getElementById('sum-total-pnl').innerHTML = '$0.00';
                document.getElementById('sum-total-pnl').className = 'summary-main neutral';
                document.getElementById('sum-total-pct').innerHTML = 'No fills in this window';
                document.getElementById('sum-trading-pnl').innerHTML = '$0.00';
                document.getElementById('sum-market-pnl').innerHTML = '$0.00';
                document.getElementById('sum-funding').innerHTML = '$0.00';
                document.getElementById('sum-fills').innerHTML = '0 fills';
                document.getElementById('sum-volume').innerHTML = '$0';
                document.getElementById('sum-buysells').innerHTML = '0 / 0';
                document.getElementById('sum-fillrate').innerHTML = '0';
                document.getElementById('sum-buyhold').innerHTML = 'N/A';
                document.getElementById('sum-alpha').innerHTML = 'N/A';
                document.getElementById('sum-direction').innerHTML = 'N/A';
                document.getElementById('sum-skill').innerHTML = 'N/A';
                document.getElementById('sum-fees').innerHTML = '$0.00';
                document.getElementById('sum-hourly').innerHTML = '$0.00';
                document.getElementById('sum-monthly-roi').innerHTML = '0%/mo';
                document.getElementById('sum-drawdown').innerHTML = 'N/A';
                document.getElementById('sum-markout').innerHTML = 'N/A';
                document.getElementById('sum-neg-fills').innerHTML = 'N/A';
                document.getElementById('sum-imbalance').innerHTML = 'N/A';
                document.getElementById('sum-duration').innerHTML = '0 hrs';
                // Keep live position and funding rate updated even with no window data
                updateLivePositionCards(lp);
                return;
            }

            // Total P&L card
            document.getElementById('sum-total-pnl').innerHTML = formatPnL(w.total_pnl);
            document.getElementById('sum-total-pnl').className = 'summary-main ' + getPnLClass(w.total_pnl);

            const totalPct = w.start_value ? (w.total_pnl / w.start_value * 100).toFixed(2) : 0;
            const projectedDaily = w.hours > 0 ? (w.total_pnl / w.hours * 24).toFixed(2) : 0;
            document.getElementById('sum-total-pct').innerHTML = `${totalPct >= 0 ? '+' : ''}${totalPct}% | $${projectedDaily}/day projected`;

            document.getElementById('sum-trading-pnl').innerHTML = formatPnL(w.realized_pnl);
            document.getElementById('sum-trading-pnl').className = getPnLClass(w.realized_pnl);

            document.getElementById('sum-market-pnl').innerHTML = formatPnL(w.unrealized_pnl);
            document.getElementById('sum-market-pnl').className = getPnLClass(w.unrealized_pnl);

            document.getElementById('sum-funding').innerHTML = formatPnL(w.funding || 0);
            document.getElementById('sum-funding').className = getPnLClass(w.funding || 0);

            // Trading Activity card
            document.getElementById('sum-fills').innerHTML = w.fills + ' fills';
            document.getElementById('sum-volume').innerHTML = '$' + w.volume.toFixed(0);
            document.getElementById('sum-buysells').innerHTML = `${w.buy_fills} / ${w.sell_fills}`;
            const fillRate = w.hours > 0 ? (w.fills / w.hours).toFixed(1) : 0;
            document.getElementById('sum-fillrate').innerHTML = fillRate;

            // Strategy Analysis card
            const startingValue = w.start_value || 100;
            const buyHoldPnl = startingValue * (w.end_price - w.start_price) / w.start_price;
            const alpha = w.total_pnl - buyHoldPnl;

            const positionChange = w.base_delta;
            const priceChange = w.end_price - w.start_price;
            const marketDirectionPnl = positionChange * priceChange;
            const tradingSkillPnl = w.realized_pnl - marketDirectionPnl;

            document.getElementById('sum-buyhold').innerHTML = formatPnL(buyHoldPnl);
            document.getElementById('sum-buyhold').className = getPnLClass(buyHoldPnl);
            document.getElementById('sum-alpha').innerHTML = formatPnL(alpha);
            document.getElementById('sum-alpha').className = getPnLClass(alpha);
            document.getElementById('sum-direction').innerHTML = formatPnL(marketDirectionPnl);
            document.getElementById('sum-direction').className = getPnLClass(marketDirectionPnl);
            document.getElementById('sum-skill').innerHTML = formatPnL(tradingSkillPnl);
            document.getElementById('sum-skill').className = getPnLClass(tradingSkillPnl);

            // Live Position and Funding Rate cards (always update)
            updateLivePositionCards(lp);

            // Performance card
            document.getElementById('sum-fees').innerHTML = '-$' + w.fees.toFixed(2);
            document.getElementById('sum-fees').className = 'negative';
            document.getElementById('sum-hourly').innerHTML = formatPnL(w.pnl_per_hour) + '/hr';
            document.getElementById('sum-hourly').className = getPnLClass(w.pnl_per_hour);
            const monthlyRoi = w.start_value && w.hours > 0 ?
                (w.pnl_per_hour * 24 * 30 / w.start_value * 100).toFixed(1) : 0;
            document.getElementById('sum-monthly-roi').innerHTML = `${monthlyRoi}%/mo`;
            document.getElementById('sum-duration').innerHTML = w.hours.toFixed(1) + ' hrs';

            // Drawdown
            if (cachedData.drawdown) {
                const dd = cachedData.drawdown;
                const ddPct = dd.drawdown_pct;
                const ddClass = ddPct >= -5 ? 'positive' : ddPct >= -15 ? 'warning' : 'negative';
                document.getElementById('sum-drawdown').innerHTML = `<span class="${ddClass}">${ddPct.toFixed(1)}%</span>`;
            } else {
                document.getElementById('sum-drawdown').innerHTML = 'N/A';
            }

            // Toxicity Monitor card
            const toxicity = w.toxicity || {};
            if (toxicity.insufficient_data) {
                document.getElementById('sum-markout').innerHTML = 'N/A';
                document.getElementById('sum-neg-fills').innerHTML = 'N/A';
            } else {
                const markout5s = toxicity.avg_markout_5s || 0;
                const markout30s = toxicity.avg_markout_30s || 0;
                document.getElementById('sum-markout').innerHTML =
                    `<span class="${getToxicityClass(markout30s)}">${markout5s >= 0 ? '+' : ''}${markout5s.toFixed(1)}</span> / ` +
                    `<span class="${getToxicityClass(markout30s)}">${markout30s >= 0 ? '+' : ''}${markout30s.toFixed(1)}</span> bps`;

                const negFills = toxicity.pct_negative_30s || 0;
                document.getElementById('sum-neg-fills').innerHTML = `<span class="${getToxicityClass(-negFills)}">${negFills.toFixed(0)}%</span>`;
            }

            const buyPct = toxicity.buy_pct || 50;
            const sellPct = toxicity.sell_pct || 50;
            document.getElementById('sum-imbalance').innerHTML = buyPct.toFixed(0) + '% / ' + sellPct.toFixed(0) + '%';

            // Bot Settings card
            if (cachedData.parameters && cachedData.parameters.length > 0) {
                const currentParam = s ? cachedData.parameters.find(p => p.id === s.parameter_set_id) : cachedData.parameters[0];
                if (currentParam) {
                    document.getElementById('sum-order-size').innerHTML = currentParam.order_size || 'N/A';
                    document.getElementById('sum-spread').innerHTML = (currentParam.spread_bps || 0) + ' bps';
                    document.getElementById('sum-max-pos').innerHTML = (currentParam.max_position || 0) + ' USD';
                }
            }

            checkAlerts(w, s, toxicity, lp);
        }

        function checkAlerts(windowData, status, toxicity, livePosition) {
            const alerts = [];

            if (!toxicity.insufficient_data && toxicity.pct_negative_30s > 70) {
                alerts.push({
                    type: 'critical',
                    icon: '🔴',
                    message: `TOXIC FILLS: ${toxicity.pct_negative_30s.toFixed(0)}% of fills are negative`
                });
            }

            if (livePosition && livePosition.margin) {
                const marginRatio = livePosition.margin.margin_ratio_pct;
                // Only show margin alert if there's actually a position (marginRatio is not null)
                if (marginRatio !== null && marginRatio !== undefined && marginRatio < 150) {
                    alerts.push({
                        type: 'critical',
                        icon: '⚠️',
                        message: `LOW MARGIN: ${marginRatio.toFixed(0)}% margin ratio - liquidation risk!`
                    });
                }
            }

            if (windowData.hours >= 0.5 && windowData.fills === 0) {
                alerts.push({
                    type: 'warning',
                    icon: '😴',
                    message: `NO FILLS: Bot hasn't filled in ${windowData.hours.toFixed(1)} hours`
                });
            }

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

                    cachedData = data;
                    document.getElementById('updated-at').textContent = new Date(data.updated_at).toLocaleString();
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

                        document.getElementById('mid-price').innerHTML = '$' + (s.mid_price || 0).toFixed(4);

                        if (s.our_bid_price && s.our_ask_price) {
                            const spread = s.our_ask_price - s.our_bid_price;
                            const spreadBps = (spread / s.mid_price * 10000).toFixed(0);
                            document.getElementById('our-spread').innerHTML = spreadBps + ' bps';
                        }

                        document.getElementById('current-position').innerHTML = (s.base_total || 0).toFixed(4) + ' {{ market_name }}';
                    }

                    // Update parameter changes timeline
                    const changesContainer = document.getElementById('param-changes-container');
                    if (data.parameter_changes && data.parameter_changes.length > 0) {
                        let changesHtml = '';
                        for (const change of data.parameter_changes) {
                            const timestamp = new Date(change.timestamp).toLocaleString();
                            changesHtml += `
                                <div class="timeline-item">
                                    <div class="timeline-header">
                                        <span class="timeline-timestamp">${timestamp}</span>
                                        <span class="timeline-reason">${change.reason || 'manual'}</span>
                                    </div>
                                    ${change.change_summary ? `<div style="color: #e0e0e0; margin-bottom: 8px;">${change.change_summary}</div>` : ''}
                                    <div class="timeline-change">
                                        <div class="timeline-old">Config #${change.old_param_id || 'N/A'}</div>
                                        <div class="timeline-arrow">→</div>
                                        <div class="timeline-new">Config #${change.new_param_id}</div>
                                    </div>
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

        function updateFills() {
            fetch('api/fills?limit=20')
                .then(r => r.json())
                .then(data => {
                    const fills = data.fills || [];
                    if (fills.length === 0) {
                        document.getElementById('fills-body').innerHTML = '<tr><td colspan="7" style="color: #888;">No fills yet</td></tr>';
                        return;
                    }

                    let html = '';
                    for (const f of fills) {
                        const sideClass = f.side === 'buy' ? 'positive' : 'negative';
                        const pnlClass = f.pnl > 0 ? 'positive' : f.pnl < 0 ? 'negative' : '';
                        const time = new Date(f.timestamp).toLocaleTimeString();

                        html += `
                            <tr>
                                <td>${time}</td>
                                <td class="${sideClass}">${f.side.toUpperCase()}</td>
                                <td>$${f.price.toFixed(4)}</td>
                                <td>${f.size.toFixed(4)}</td>
                                <td>$${f.value.toFixed(2)}</td>
                                <td class="negative">-$${f.fee.toFixed(4)}</td>
                                <td class="${pnlClass}">${f.pnl >= 0 ? '+' : ''}$${f.pnl.toFixed(4)}</td>
                            </tr>
                        `;
                    }
                    document.getElementById('fills-body').innerHTML = html;
                })
                .catch(err => console.error('Fills fetch error:', err));
        }

        // Position Chart
        let positionChart = null;
        let selectedChartWindow = 4;

        function selectChartWindow(window) {
            selectedChartWindow = window;
            document.querySelectorAll('.chart-window-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelector(`[data-chart-window="${window}"]`).classList.add('active');
            updatePositionChart();
        }

        function updatePositionChart() {
            fetch('api/position_chart?window=' + encodeURIComponent(selectedChartWindow))
                .then(r => r.json())
                .then(data => {
                    if (!data.success) {
                        document.getElementById('chart-insights').innerHTML =
                            '<div class="chart-insight-item">⚠️ No data available for this time window</div>';
                        return;
                    }

                    const chartData = data.chart_data;

                    const insightsHtml = chartData.insights.map(insight =>
                        `<div class="chart-insight-item">💡 ${insight}</div>`
                    ).join('');
                    document.getElementById('chart-insights').innerHTML = insightsHtml;

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

            if (positionChart) {
                positionChart.destroy();
            }

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
                            pointRadius: 1,
                            tension: 0.1
                        },
                        {
                            label: 'Position',
                            data: chartData.positions,
                            borderColor: '#00ff88',
                            backgroundColor: 'rgba(0, 255, 136, 0.2)',
                            borderWidth: 2,
                            yAxisID: 'y-position',
                            pointRadius: 1,
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
                                font: { family: "'SF Mono', monospace", size: 12 }
                            }
                        },
                        tooltip: {
                            backgroundColor: '#1a2140',
                            titleColor: '#00ccff',
                            bodyColor: '#e0e0e0',
                            borderColor: '#00ccff',
                            borderWidth: 1
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: '#2a3359' },
                            ticks: { color: '#888', font: { size: 10 }, maxRotation: 45, minRotation: 45 }
                        },
                        'y-price': {
                            type: 'linear',
                            position: 'left',
                            grid: { color: '#2a3359' },
                            ticks: {
                                color: '#00ccff',
                                callback: function(value) { return '$' + value.toFixed(2); }
                            },
                            title: { display: true, text: 'Price (USD)', color: '#00ccff' }
                        },
                        'y-position': {
                            type: 'linear',
                            position: 'right',
                            grid: { display: false },
                            ticks: {
                                color: '#00ff88',
                                callback: function(value) { return value.toFixed(2); }
                            },
                            title: { display: true, text: 'Position', color: '#00ff88' }
                        }
                    }
                }
            });
        }

        // Initial load
        updateDashboard();
        updateFills();
        updatePositionChart();

        // Refresh every 60 seconds
        setInterval(updateDashboard, 60000);
        setInterval(updateFills, 30000);
        setInterval(updatePositionChart, 60000);

        // =========================================
        // BOT CONTROL FUNCTIONS
        // =========================================
        const CONFIG_FILE = '{{ config_file or "" }}';

        function updateBotStatus(running, pid, uptime) {
            const dot = document.getElementById('botStatusDot');
            const text = document.getElementById('botStatusText');
            const uptimeEl = document.getElementById('botUptime');
            const btnStart = document.getElementById('btnStart');
            const btnStop = document.getElementById('btnStop');

            if (!dot) return; // No config file linked

            if (running) {
                dot.className = 'status-dot running';
                text.className = 'status-text running';
                text.textContent = 'Running (PID: ' + (pid || '?') + ')';
                uptimeEl.textContent = uptime ? '• ' + uptime : '';
                btnStart.style.display = 'none';
                btnStop.style.display = 'inline-block';
                btnStop.disabled = false;
                btnStop.textContent = 'Stop Bot';
            } else {
                dot.className = 'status-dot';
                text.className = 'status-text';
                text.textContent = 'Stopped';
                uptimeEl.textContent = '';
                btnStart.style.display = 'inline-block';
                btnStart.disabled = false;
                btnStart.textContent = 'Start Bot';
                btnStop.style.display = 'none';
            }
        }

        async function checkBotStatus() {
            if (!CONFIG_FILE) return;
            try {
                const resp = await fetch('/config/api/bot/status/' + CONFIG_FILE);
                const data = await resp.json();
                updateBotStatus(data.running, data.pid, data.uptime);
            } catch (err) {
                console.error('Error checking bot status:', err);
            }
        }

        async function startBot() {
            if (!CONFIG_FILE) return;
            const btn = document.getElementById('btnStart');
            btn.disabled = true;
            btn.textContent = 'Starting...';

            try {
                const resp = await fetch('/config/api/bot/start/' + CONFIG_FILE, { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    updateBotStatus(true, data.pid);
                } else {
                    alert('Failed to start bot: ' + (data.error || 'Unknown error'));
                    btn.disabled = false;
                    btn.textContent = 'Start Bot';
                }
            } catch (err) {
                alert('Error starting bot: ' + err.message);
                btn.disabled = false;
                btn.textContent = 'Start Bot';
            }
        }

        async function stopBot() {
            if (!CONFIG_FILE) return;
            const btn = document.getElementById('btnStop');
            btn.disabled = true;
            btn.textContent = 'Stopping...';

            try {
                const resp = await fetch('/config/api/bot/stop/' + CONFIG_FILE, { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    updateBotStatus(false);
                } else {
                    alert('Failed to stop bot: ' + (data.error || 'Unknown error'));
                    btn.disabled = false;
                    btn.textContent = 'Stop Bot';
                }
            } catch (err) {
                alert('Error stopping bot: ' + err.message);
                btn.disabled = false;
                btn.textContent = 'Stop Bot';
            }
        }

        async function stopAllBots() {
            if (!confirm('Stop all bots and cancel all open orders?')) return;
            try {
                const resp = await fetch('/api/stop_all', { method: 'POST' });
                const data = await resp.json();
                let msg = 'Stopped ' + data.processes_killed + ' bot(s)';
                msg += '\\nCancelled ' + data.orders_cancelled + ' order(s)';
                if (data.errors && data.errors.length > 0) {
                    msg += '\\n\\nWarnings: ' + data.errors.join(', ');
                }
                alert(msg);
                checkBotStatus();
            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        async function clearData() {
            const market = '{{ market_name }}-PERP';
            if (!confirm('Clear all historical data for ' + market + '?\\n\\nThis will delete all metrics and fill records for this market only. This cannot be undone.')) {
                return;
            }

            try {
                const resp = await fetch('/{{ route_prefix }}/api/clear_data', { method: 'POST' });
                const data = await resp.json();
                if (data.success) {
                    alert('Cleared data for ' + market + ':\\n- ' + data.deleted.metrics + ' metric records\\n- ' + data.deleted.fills + ' fill records');
                    // Refresh the dashboard
                    updateDashboard();
                    updateFills();
                    updatePositionChart();
                } else {
                    alert('Error clearing data: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Error clearing data: ' + err.message);
            }
        }

        // Check bot status on load and periodically
        if (CONFIG_FILE) {
            checkBotStatus();
            setInterval(checkBotStatus, 5000);
        }

    </script>
    <!-- Footer + AI Chat injected automatically by after_request -->
</body>
</html>
'''

    return bp
