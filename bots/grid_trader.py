#!/usr/bin/env python3
"""
Grid Trading Bot for Hyperliquid Perpetuals
Places orders at fixed price levels, profits from price oscillation
Supports directional bias (long/short/neutral)

Perp Lobster - Powered by Vibetrade.cc
"""

import json
import time
import sqlite3
import argparse
import sys
import os
import signal
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from config_loader import ConfigLoader
from websocket_integration import MarketDataWebSocket
from parameter_manager import ParameterManager
from metrics_capture import MetricsCapture
from credentials import get_builder

# ============================================================
# PARSE COMMAND LINE ARGUMENTS
# ============================================================

parser = argparse.ArgumentParser(description='Grid trading bot for Hyperliquid perpetuals')
parser.add_argument('--config', required=True, help='Path to config file (e.g., config/copper_grid_config.json)')
args = parser.parse_args()

# ============================================================
# CONFIGURATION - LOAD FROM FILE
# ============================================================

print(f"Loading configuration from {args.config}...")
with open(args.config) as f:
    CONFIG = json.load(f)
print("Configuration loaded")

# Extract market info
MARKET_NAME = CONFIG['market']  # e.g., "xyz:COPPER" for builder markets
DEX = CONFIG.get('dex', '')  # e.g., "xyz", "flx", or "" for main markets
MARKET_DISPLAY = f"{MARKET_NAME}-PERP"  # Dashboard expects "-PERP" suffix
IS_HIP3_MARKET = DEX != ''  # HIP-3 markets need special handling

# Grid settings
GRID_SPACING_PCT = CONFIG['grid']['spacing_pct']  # % between levels
NUM_LEVELS_EACH_SIDE = CONFIG['grid']['num_levels_each_side']  # levels above + below
ORDER_SIZE_USD = CONFIG['grid']['order_size_usd']  # USD per order
REBALANCE_THRESHOLD_PCT = CONFIG['grid'].get('rebalance_threshold_pct', 3.0)  # Rebalance if price moves this far from center
BIAS = CONFIG['grid'].get('bias', 'neutral')  # 'long', 'short', or 'neutral'

# Position limits
MAX_POSITION_USD = CONFIG['position']['max_position_usd']
LEVERAGE = CONFIG['position'].get('leverage', 5)

# Timing
FILL_CHECK_SECONDS = CONFIG['timing'].get('fill_check_seconds', 5)
HEALTH_CHECK_SECONDS = CONFIG['timing'].get('health_check_seconds', 60)

# Safety
MAX_OPEN_ORDERS = CONFIG['safety'].get('max_open_orders', 20)
EMERGENCY_STOP_LOSS_PCT = CONFIG['safety'].get('emergency_stop_loss_pct', -15.0)
MIN_MARGIN_RATIO_PCT = CONFIG['safety'].get('min_margin_ratio_pct', 10.0)
PAUSE_ON_HIGH_VOLATILITY = CONFIG['safety'].get('pause_on_high_volatility', True)
VOLATILITY_THRESHOLD_PCT = CONFIG['safety'].get('volatility_threshold_pct', 5.0)
MAX_ACCOUNT_DRAWDOWN_PCT = CONFIG['safety'].get('max_account_drawdown_pct', -20.0)  # Max % loss from session start
CLOSE_POSITION_ON_EMERGENCY = CONFIG['safety'].get('close_position_on_emergency', True)  # Close position when stopping

# Exchange config
PRICE_DECIMALS = CONFIG['exchange'].get('price_decimals', 4)
SIZE_DECIMALS = CONFIG['exchange'].get('size_decimals', 2)

# Account settings
SUBACCOUNT_ADDRESS = CONFIG['account'].get('subaccount_address')
IS_SUBACCOUNT = CONFIG['account'].get('is_subaccount', False)

# ============================================================
# HYPERLIQUID API SETUP
# ============================================================

# Load credentials from .env (falls back to config.json)
print("Loading credentials...")
package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(package_root, 'lib'))
from credentials import get_credentials
credentials = get_credentials()

secret_key = credentials["secret_key"]
account = Account.from_key(secret_key)
account_address = SUBACCOUNT_ADDRESS if IS_SUBACCOUNT else account.address

print(f"Trading account: {account_address}")
if IS_SUBACCOUNT:
    print(f"   (Subaccount of {account.address})")
if IS_HIP3_MARKET:
    print(f"HIP-3 market detected: {MARKET_NAME} on {DEX}")

# Setup Hyperliquid API with HIP-3 support
base_url = constants.MAINNET_API_URL
perp_dexs = ["", "xyz", "flx"] if IS_HIP3_MARKET else None

info = Info(base_url=base_url, skip_ws=True, perp_dexs=perp_dexs) if IS_HIP3_MARKET else Info(base_url, skip_ws=True)

exchange = Exchange(
    wallet=account,
    base_url=base_url,
    account_address=account_address,
    vault_address=SUBACCOUNT_ADDRESS if IS_SUBACCOUNT else None,
    perp_dexs=perp_dexs
) if IS_HIP3_MARKET else Exchange(
    wallet=account,
    base_url=base_url,
    vault_address=SUBACCOUNT_ADDRESS if IS_SUBACCOUNT else None
)

# ============================================================
# PARAMETER MANAGER - Track config changes
# ============================================================

param_manager = ParameterManager(pair=MARKET_NAME)

# Build current config dict for tracking
# Map grid fields to parameter_manager expected fields
current_config = {
    # Grid-specific fields
    'grid_spacing_pct': GRID_SPACING_PCT,
    'num_levels_each_side': NUM_LEVELS_EACH_SIDE,
    'order_size_usd': ORDER_SIZE_USD,
    'rebalance_threshold_pct': REBALANCE_THRESHOLD_PCT,
    'bias': BIAS,
    'max_position_usd': MAX_POSITION_USD,
    'leverage': LEVERAGE,
    'fill_check_seconds': FILL_CHECK_SECONDS,
    'health_check_seconds': HEALTH_CHECK_SECONDS,
    'max_open_orders': MAX_OPEN_ORDERS,
    'emergency_stop_loss_pct': EMERGENCY_STOP_LOSS_PCT,
    'min_margin_ratio_pct': MIN_MARGIN_RATIO_PCT,
    'pause_on_high_volatility': PAUSE_ON_HIGH_VOLATILITY,
    'volatility_threshold_pct': VOLATILITY_THRESHOLD_PCT,
    # Map to parameter_manager expected fields (for DB compatibility)
    'base_order_size': ORDER_SIZE_USD,
    'base_spread_bps': GRID_SPACING_PCT * 100,  # Convert % to bps
    'update_interval_seconds': FILL_CHECK_SECONDS,
    'update_threshold_bps': REBALANCE_THRESHOLD_PCT * 100,
    'target_position': 0,  # Neutral
    'max_position_size': MAX_POSITION_USD,
    'inventory_skew_bps_per_unit': 0,
    'max_skew_bps': 0,
    'inventory_skew_threshold': 0,
    'smart_order_mgmt_enabled': False,
}

# Register config and check for changes
changed_id = param_manager.check_for_changes(current_config)
if changed_id:
    print(f"   ✅ Configuration updated to parameter set #{changed_id}")
else:
    print(f"   ✅ Using existing parameter set #{param_manager.get_current_id()}")

# ============================================================
# GLOBAL STATE
# ============================================================

# Grid state
grid_levels: List[float] = []  # All grid price levels
grid_center_price: float = 0.0  # Price when grid was initialized
grid_initialized_at: float = 0.0  # Timestamp when grid was initialized
level_orders: Dict[float, Dict] = {}  # level_price -> {'oid': str, 'side': 'buy'|'sell'}

# Position tracking
current_position_usd = 0.0
current_position_size = 0.0
unrealized_pnl = 0.0

# Fill tracking for profit calculation
completed_round_trips = 0
total_grid_profit = 0.0

# WebSocket
ws_client: Optional[MarketDataWebSocket] = None

# Safety flags
emergency_stop = False
paused = False
starting_account_value = 0.0  # Track account value at session start for drawdown calc

# Fill tracking for REST polling (HIP-3 markets)
last_fill_check_time = 0
processed_fill_ids = set()  # Track which fills we've already processed

# ============================================================
# MARKET DATA FUNCTIONS
# ============================================================

def get_mark_price() -> Optional[float]:
    """Get current mark price"""
    try:
        # Try WebSocket first, but check for staleness
        if ws_client:
            orderbook = ws_client.get_orderbook()
            if orderbook:
                # Check if data is fresh (within last 10 seconds)
                data_age = time.time() - orderbook.get('timestamp', 0)
                if data_age < 10:
                    return orderbook['mid']
                else:
                    print(f"   WebSocket data stale ({data_age:.1f}s old), using REST")

        # Fallback to REST API - different handling for HIP-3 markets
        if IS_HIP3_MARKET:
            # HIP-3 markets need POST request with dex parameter
            payload = {"type": "l2Book", "coin": MARKET_NAME, "dex": DEX}
            l2_data = info.post("/info", payload)
        else:
            l2_data = info.l2_snapshot(MARKET_NAME)

        if not l2_data or 'levels' not in l2_data:
            return None

        levels = l2_data['levels']
        if len(levels) < 2 or not levels[0] or not levels[1]:
            return None

        best_bid = float(levels[0][0]['px'])
        best_ask = float(levels[1][0]['px'])
        return (best_bid + best_ask) / 2

    except Exception as e:
        print(f"Error fetching mark price: {e}")
        return None


def get_position() -> Dict:
    """Get current position"""
    try:
        if IS_HIP3_MARKET:
            user_state = info.user_state(account_address, dex=DEX)
        else:
            user_state = info.user_state(account_address)
        asset_positions = user_state.get('assetPositions', [])

        # Find our market's position
        perp_position = next(
            (p for p in asset_positions if p['position']['coin'] == MARKET_NAME),
            None
        )

        if not perp_position:
            return {
                'size': 0.0,
                'entry_px': 0.0,
                'position_value': 0.0,
                'unrealized_pnl': 0.0
            }

        pos_data = perp_position['position']
        size = float(pos_data.get('szi', 0.0))
        entry_px = float(pos_data.get('entryPx', 0.0)) if size != 0 else 0.0
        position_value = float(pos_data.get('positionValue', 0.0))
        position_value = position_value if size >= 0 else -position_value
        unrealized_pnl = float(pos_data.get('unrealizedPnl', 0.0))

        return {
            'size': size,
            'entry_px': entry_px,
            'position_value': position_value,
            'unrealized_pnl': unrealized_pnl
        }

    except Exception as e:
        print(f"Error fetching position: {e}")
        return {'size': 0.0, 'entry_px': 0.0, 'position_value': 0.0, 'unrealized_pnl': 0.0}


def get_account_value() -> Dict:
    """Get account value and margin info"""
    try:
        user_state = info.user_state(account_address)
        margin_summary = user_state.get('marginSummary', {})

        account_value = float(margin_summary.get('accountValue', 0.0))
        total_margin_used = float(margin_summary.get('totalMarginUsed', 0.0))
        margin_ratio_pct = (account_value / total_margin_used * 100) if total_margin_used > 0 else 0

        return {
            'account_value': account_value,
            'total_margin_used': total_margin_used,
            'margin_ratio_pct': margin_ratio_pct
        }

    except Exception as e:
        print(f"Error fetching account value: {e}")
        return {'account_value': 0.0, 'total_margin_used': 0.0, 'margin_ratio_pct': 0.0}


# Global for metrics - track last known price
last_mark_price = None


def get_bot_state_for_metrics():
    """Return bot state for metrics logging"""
    global last_mark_price

    position = get_position()
    account_info = get_account_value()
    open_orders = get_open_orders()

    # Get current price
    current_price = get_mark_price()
    if current_price:
        last_mark_price = current_price

    # Position size in contracts
    pos_size = position['size']

    # Check for live orders (bids and asks)
    bid_orders = [o for o in open_orders if o.get('side') == 'B']
    ask_orders = [o for o in open_orders if o.get('side') == 'A']
    bid_live = len(bid_orders) > 0
    ask_live = len(ask_orders) > 0

    # Get best bid/ask prices from our orders
    our_bid_price = max([float(o['limitPx']) for o in bid_orders]) if bid_orders else None
    our_ask_price = min([float(o['limitPx']) for o in ask_orders]) if ask_orders else None

    return {
        'mid_price': last_mark_price or 0.0,
        'position_size': pos_size,
        'position_value': position['position_value'],
        'unrealized_pnl': position['unrealized_pnl'],
        'account_value': account_info['account_value'],
        'margin_ratio': account_info['margin_ratio_pct'],
        'total_value_usd': account_info['account_value'],
        'base_total': pos_size,  # Position in contracts
        'quote_total': account_info['account_value'],  # Account equity (USD)
        'bot_running': True,
        'bid_live': bid_live,
        'ask_live': ask_live,
        'our_bid_price': our_bid_price,
        'our_ask_price': our_ask_price,
        'spread_bps': GRID_SPACING_PCT * 100,  # Grid spacing as spread
    }


# ============================================================
# ORDER MANAGEMENT
# ============================================================

def get_open_orders() -> List[Dict]:
    """Get all open orders for this market"""
    try:
        if IS_HIP3_MARKET:
            open_orders = info.open_orders(account_address, dex=DEX)
        else:
            open_orders = info.open_orders(account_address)
        return [o for o in open_orders if o.get('coin') == MARKET_NAME]
    except Exception as e:
        print(f"Error fetching open orders: {e}")
        return []


def has_order_at_price(target_price: float, tolerance_pct: float = 0.05) -> bool:
    """Check if there's already an open order at or near this price level"""
    try:
        open_orders = get_open_orders()
        for order in open_orders:
            order_price = float(order.get('limitPx', 0))
            if order_price > 0:
                price_diff_pct = abs(order_price - target_price) / target_price * 100
                if price_diff_pct < tolerance_pct:
                    return True
        return False
    except Exception as e:
        print(f"Error checking orders at price: {e}")
        return False


def cancel_all_orders():
    """Cancel all open orders for this market"""
    try:
        open_orders = get_open_orders()
        for order in open_orders:
            try:
                exchange.cancel(MARKET_NAME, order['oid'])
                print(f"   Cancelled order {order['oid']}")
            except Exception as e:
                print(f"   Error cancelling {order['oid']}: {e}")
        return len(open_orders)
    except Exception as e:
        print(f"Error cancelling orders: {e}")
        return 0


def cancel_order(oid: str) -> bool:
    """Cancel a specific order"""
    try:
        exchange.cancel(MARKET_NAME, oid)
        return True
    except Exception as e:
        print(f"Error cancelling order {oid}: {e}")
        return False


def close_position() -> bool:
    """Close the entire position with a market order"""
    try:
        position = get_position()
        size = abs(position['size'])

        if size < 0.001:  # No meaningful position
            print("   No position to close")
            return True

        # If long, sell to close. If short, buy to close.
        is_long = position['size'] > 0

        print(f"   Closing {'LONG' if is_long else 'SHORT'} position: {size} contracts")

        # Place market order to close
        order_result = exchange.market_close(MARKET_NAME, builder=get_builder())

        if order_result and order_result.get('status') == 'ok':
            print(f"   Position closed successfully")
            return True
        else:
            print(f"   Error closing position: {order_result}")
            return False

    except Exception as e:
        print(f"Error closing position: {e}")
        return False


def get_current_bbo() -> Tuple[Optional[float], Optional[float]]:
    """Get current best bid and ask"""
    try:
        if IS_HIP3_MARKET:
            payload = {"type": "l2Book", "coin": MARKET_NAME, "dex": DEX}
            l2_data = info.post("/info", payload)
        else:
            l2_data = info.l2_snapshot(MARKET_NAME)

        if not l2_data or 'levels' not in l2_data:
            return None, None

        levels = l2_data['levels']
        if len(levels) < 2 or not levels[0] or not levels[1]:
            return None, None

        best_bid = float(levels[0][0]['px'])
        best_ask = float(levels[1][0]['px'])
        return best_bid, best_ask
    except:
        return None, None


def place_order(is_buy: bool, price: float, size_contracts: float) -> Tuple[bool, Optional[str]]:
    """Place a limit order (post-only)"""
    try:
        price = round(price, PRICE_DECIMALS)
        size_contracts = round(size_contracts, SIZE_DECIMALS)

        if size_contracts < 0.01:  # Min size
            return False, None

        # Check if order would cross spread (post-only would be rejected)
        best_bid, best_ask = get_current_bbo()
        if best_bid and best_ask:
            if is_buy and price >= best_ask:
                print(f"      Skipping BUY at ${price:.4f} - would cross spread (ask: ${best_ask:.4f})")
                return False, None
            if not is_buy and price <= best_bid:
                print(f"      Skipping SELL at ${price:.4f} - would cross spread (bid: ${best_bid:.4f})")
                return False, None

        # Use post-only (ALO) for maker orders
        order_type = {"limit": {"tif": "Alo"}}

        result = exchange.order(
            MARKET_NAME,
            is_buy,
            size_contracts,
            price,
            order_type,
            False,  # reduce_only
            builder=get_builder()
        )

        if result.get("status") == "ok":
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            if statuses and "resting" in statuses[0]:
                oid = statuses[0]["resting"]["oid"]
                return True, oid
            elif statuses and "error" in statuses[0]:
                error_msg = statuses[0].get("error", "Unknown error")
                print(f"      Order error: {error_msg}")
                return False, None

        return False, None

    except Exception as e:
        print(f"Error placing {'buy' if is_buy else 'sell'} order: {e}")
        return False, None


# ============================================================
# GRID LOGIC
# ============================================================

def calculate_grid_levels(center_price: float) -> List[float]:
    """
    Calculate grid price levels around center price

    For 'long' bias: more levels below (buys) than above (sells)
    For 'short' bias: more levels above (sells) than below (buys)
    For 'neutral': equal levels on both sides
    """
    levels = []
    spacing_multiplier = 1 + (GRID_SPACING_PCT / 100)

    # Determine level distribution based on bias
    if BIAS == 'long':
        levels_below = NUM_LEVELS_EACH_SIDE + 2  # Extra buy levels
        levels_above = max(2, NUM_LEVELS_EACH_SIDE - 2)  # Fewer sell levels
    elif BIAS == 'short':
        levels_below = max(2, NUM_LEVELS_EACH_SIDE - 2)
        levels_above = NUM_LEVELS_EACH_SIDE + 2
    else:  # neutral
        levels_below = NUM_LEVELS_EACH_SIDE
        levels_above = NUM_LEVELS_EACH_SIDE

    # Generate levels below center (buy zone)
    for i in range(1, levels_below + 1):
        level = center_price / (spacing_multiplier ** i)
        levels.append(round(level, PRICE_DECIMALS))

    # Generate levels above center (sell zone)
    for i in range(1, levels_above + 1):
        level = center_price * (spacing_multiplier ** i)
        levels.append(round(level, PRICE_DECIMALS))

    # Sort levels
    levels.sort()

    return levels


def initialize_grid(current_price: float):
    """Initialize or reinitialize the grid around current price"""
    global grid_levels, grid_center_price, grid_initialized_at, level_orders

    print(f"\n{'='*60}")
    print(f"INITIALIZING GRID")
    print(f"{'='*60}")
    print(f"Center price: ${current_price:.{PRICE_DECIMALS}f}")
    print(f"Spacing: {GRID_SPACING_PCT}%")
    print(f"Bias: {BIAS}")

    # Cancel existing orders
    cancelled = cancel_all_orders()
    if cancelled > 0:
        print(f"Cancelled {cancelled} existing orders")
        time.sleep(1)

    # Calculate new grid levels
    grid_center_price = current_price
    grid_initialized_at = time.time() * 1000  # milliseconds for comparison with fill timestamps
    grid_levels = calculate_grid_levels(current_price)
    level_orders = {}

    print(f"\nGrid levels ({len(grid_levels)} total):")
    for level in grid_levels:
        side = "BUY" if level < current_price else "SELL"
        print(f"   ${level:.{PRICE_DECIMALS}f} [{side}]")

    # Place initial orders
    place_grid_orders(current_price)

    print(f"{'='*60}\n")


def place_grid_orders(current_price: float):
    """Place orders at grid levels that don't have orders"""
    global level_orders

    position = get_position()
    position_usd = position['position_value']

    orders_placed = 0

    for level in grid_levels:
        # Skip if level already has an order (check both local tracking AND exchange)
        if level in level_orders or has_order_at_price(level):
            continue

        # Determine side based on level vs GRID CENTER (not current price!)
        # This ensures buy levels stay buy levels even if price moves
        is_buy = level < grid_center_price

        # Check position limits
        order_usd = ORDER_SIZE_USD

        if is_buy:
            # Buying would increase long / decrease short
            projected_position = position_usd + order_usd
            if projected_position > MAX_POSITION_USD:
                print(f"   Skipping BUY at ${level:.{PRICE_DECIMALS}f} - would exceed max long position")
                continue
        else:
            # Selling would decrease long / increase short
            projected_position = position_usd - order_usd
            if projected_position < -MAX_POSITION_USD:
                print(f"   Skipping SELL at ${level:.{PRICE_DECIMALS}f} - would exceed max short position")
                continue

        # Calculate size in contracts
        size_contracts = order_usd / level

        # Place order
        success, oid = place_order(is_buy, level, size_contracts)

        if success:
            level_orders[level] = {
                'oid': oid,
                'side': 'buy' if is_buy else 'sell',
                'size': size_contracts,
                'placed_at': time.time()
            }
            orders_placed += 1
            side_str = "BUY" if is_buy else "SELL"
            print(f"   Placed {side_str} at ${level:.{PRICE_DECIMALS}f} x {size_contracts:.{SIZE_DECIMALS}f}")

        # Rate limiting
        if orders_placed >= 3:
            time.sleep(0.5)

    print(f"Placed {orders_placed} grid orders")


def handle_fill(fill: Dict):
    """
    Handle a fill event - place opposite order at adjacent grid level

    When BUY fills at level N -> place SELL at level N+1
    When SELL fills at level N -> place BUY at level N-1
    """
    global level_orders, completed_round_trips, total_grid_profit

    fill_price = float(fill.get('px', 0))
    fill_side = fill.get('side', '').upper()  # 'B' or 'A'
    fill_size = float(fill.get('sz', 0))
    fill_fee = float(fill.get('fee', 0))
    fill_time = int(fill.get('time', 0))

    # Ignore fills that happened before grid was initialized
    if grid_initialized_at > 0 and fill_time < grid_initialized_at:
        print(f"   [Ignoring old fill from before grid init: {fill_price} @ {fill_time}]")
        return

    is_buy_fill = fill_side == 'B'

    print(f"\n{'*'*60}")
    print(f"FILL DETECTED")
    print(f"{'*'*60}")
    print(f"   Side: {'BUY' if is_buy_fill else 'SELL'}")
    print(f"   Price: ${fill_price:.{PRICE_DECIMALS}f}")
    print(f"   Size: {fill_size:.{SIZE_DECIMALS}f}")
    print(f"   Fee: ${fill_fee:.4f}")

    # Find which grid level this fill corresponds to
    filled_level = None
    tolerance = fill_price * 0.001  # 0.1% tolerance for price matching

    for level in grid_levels:
        if abs(level - fill_price) < tolerance:
            filled_level = level
            break

    if filled_level is None:
        print(f"   Could not match fill to grid level")
        return

    print(f"   Matched to grid level: ${filled_level:.{PRICE_DECIMALS}f}")

    # Save order info BEFORE removing (for round trip calculation)
    filled_order_info = level_orders.get(filled_level, {})

    # Remove the filled level from tracking
    if filled_level in level_orders:
        del level_orders[filled_level]

    # Find adjacent level for opposite order
    level_idx = grid_levels.index(filled_level)

    if is_buy_fill:
        # Buy filled -> place sell at next level UP
        if level_idx < len(grid_levels) - 1:
            next_level = grid_levels[level_idx + 1]

            # Skip if order already exists at this level (check both local tracking AND exchange)
            if next_level in level_orders or has_order_at_price(next_level):
                print(f"   Order already exists at ${next_level:.{PRICE_DECIMALS}f}, skipping")
            else:
                # Check if this completes a round trip (sell after buy)
                # Profit = (sell_price - buy_price) * size - fees
                expected_profit = (next_level - fill_price) * fill_size - fill_fee

                print(f"   Placing SELL at ${next_level:.{PRICE_DECIMALS}f}")
                print(f"   Expected profit if filled: ${expected_profit:.4f}")

                size_contracts = ORDER_SIZE_USD / next_level
                success, oid = place_order(False, next_level, size_contracts)

                if success:
                    level_orders[next_level] = {
                        'oid': oid,
                        'side': 'sell',
                        'size': size_contracts,
                        'placed_at': time.time(),
                        'paired_with': fill_price  # Track the buy price for profit calc
                    }
    else:
        # Sell filled -> place buy at next level DOWN
        if level_idx > 0:
            next_level = grid_levels[level_idx - 1]

            # If this sell was paired with a buy, calculate profit
            if 'paired_with' in filled_order_info:
                buy_price = filled_order_info['paired_with']
                profit = (fill_price - buy_price) * fill_size - fill_fee
                completed_round_trips += 1
                total_grid_profit += profit
                print(f"   ROUND TRIP COMPLETE!")
                print(f"   Bought at ${buy_price:.{PRICE_DECIMALS}f}, sold at ${fill_price:.{PRICE_DECIMALS}f}")
                print(f"   Profit: ${profit:.4f}")
                print(f"   Total round trips: {completed_round_trips}, Total profit: ${total_grid_profit:.4f}")

            # Skip if order already exists at this level (check both local tracking AND exchange)
            if next_level in level_orders or has_order_at_price(next_level):
                print(f"   Order already exists at ${next_level:.{PRICE_DECIMALS}f}, skipping")
            else:
                print(f"   Placing BUY at ${next_level:.{PRICE_DECIMALS}f}")

                size_contracts = ORDER_SIZE_USD / next_level
                success, oid = place_order(True, next_level, size_contracts)

                if success:
                    level_orders[next_level] = {
                        'oid': oid,
                        'side': 'buy',
                        'size': size_contracts,
                        'placed_at': time.time()
                    }

    print(f"{'*'*60}\n")


def check_grid_rebalance(current_price: float) -> bool:
    """
    Check if grid needs to be rebalanced
    Returns True if rebalance is needed
    """
    if grid_center_price == 0:
        return True

    price_change_pct = abs(current_price - grid_center_price) / grid_center_price * 100

    if price_change_pct > REBALANCE_THRESHOLD_PCT:
        print(f"\nPrice moved {price_change_pct:.2f}% from grid center")
        print(f"   Center: ${grid_center_price:.{PRICE_DECIMALS}f}")
        print(f"   Current: ${current_price:.{PRICE_DECIMALS}f}")
        print(f"   Threshold: {REBALANCE_THRESHOLD_PCT}%")
        return True

    return False


def sync_grid_with_exchange():
    """Sync local grid state with actual exchange orders"""
    global level_orders

    open_orders = get_open_orders()
    exchange_oids = {o['oid'] for o in open_orders}

    # Remove orders from tracking that no longer exist on exchange
    levels_to_remove = []
    for level, order_info in level_orders.items():
        if order_info['oid'] not in exchange_oids:
            levels_to_remove.append(level)

    for level in levels_to_remove:
        print(f"   Order at ${level:.{PRICE_DECIMALS}f} no longer on exchange (filled or cancelled)")
        del level_orders[level]

    return len(levels_to_remove)


# ============================================================
# FILL TRACKING
# ============================================================

def check_fills_rest() -> List[Dict]:
    """Check for new fills via REST API (for HIP-3 markets)"""
    global processed_fill_ids

    try:
        if IS_HIP3_MARKET:
            # Use user_fills endpoint with dex parameter
            payload = {"type": "userFills", "user": account_address, "dex": DEX}
            response = info.post("/info", payload)
        else:
            response = info.user_fills(account_address)

        if not response:
            return []

        # Filter to our market and new fills only
        new_fills = []
        for fill in response:
            fill_coin = fill.get('coin', '')
            fill_oid = fill.get('oid', '')
            fill_time = fill.get('time', 0)

            # Check if it's our market
            if fill_coin != MARKET_NAME:
                continue

            # Check if we've already processed this fill
            fill_id = f"{fill_oid}_{fill_time}"
            if fill_id in processed_fill_ids:
                continue

            # Mark as processed
            processed_fill_ids.add(fill_id)
            new_fills.append(fill)

            # Keep processed_fill_ids from growing too large
            if len(processed_fill_ids) > 1000:
                # Remove oldest entries (approximate by clearing half)
                processed_fill_ids.clear()

        return new_fills

    except Exception as e:
        print(f"Error checking fills via REST: {e}")
        return []


def record_fill_to_db(fill: Dict):
    """Record fill to database"""
    try:
        conn = sqlite3.connect('trading_data.db')
        cursor = conn.cursor()

        timestamp_ms = int(fill.get('time', 0))
        timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        timestamp = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S.%f+00:00')

        side = fill.get('side', '').lower()
        if side == 'a':
            side = 'sell'
        elif side == 'b':
            side = 'buy'

        price = float(fill.get('px', 0))
        base_amount = float(fill.get('sz', 0))
        quote_amount = price * base_amount
        fee = float(fill.get('fee', 0))

        crossed = fill.get('crossed', True)
        is_maker = 0 if crossed else 1

        closed_pnl = float(fill.get('closedPnl', 0.0))
        realized_pnl = closed_pnl - fee

        order_id = fill.get('oid', f"fill_{timestamp_ms}")

        cursor.execute("""
            INSERT OR IGNORE INTO fills
            (pair, timestamp, side, price, base_amount, quote_amount,
             fee, realized_pnl, spread_bps, order_id, is_maker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            MARKET_DISPLAY, timestamp, side, price, base_amount, quote_amount,
            fee, realized_pnl, None, order_id, is_maker
        ))

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Error recording fill to database: {e}")


# ============================================================
# MAIN LOOP
# ============================================================

def set_leverage():
    """Set leverage for this market"""
    try:
        print(f"Setting leverage to {LEVERAGE}x for {MARKET_NAME}...")

        # HIP-3 markets use isolated margin by default
        # The leverage call may need the full market name with dex prefix
        result = exchange.update_leverage(LEVERAGE, MARKET_NAME, is_cross=False)

        if result.get('status') == 'ok':
            print(f"   Leverage set to {LEVERAGE}x (isolated margin)")
        else:
            print(f"   Leverage update response: {result}")
            if IS_HIP3_MARKET:
                print(f"   Note: HIP-3 markets default to isolated margin")
                print(f"   You may need to set leverage manually in the UI")

    except Exception as e:
        print(f"   Error setting leverage: {e}")
        if IS_HIP3_MARKET:
            print(f"   HIP-3 markets use isolated margin by default")
        print(f"   Continuing anyway - may need to set leverage manually in UI")


def print_status():
    """Print current grid status"""
    position = get_position()
    account_info = get_account_value()
    current_price = get_mark_price()

    print(f"\n{'='*60}")
    print(f"GRID STATUS - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*60}")
    print(f"Market: {MARKET_DISPLAY}")
    print(f"Current price: ${current_price:.{PRICE_DECIMALS}f}" if current_price else "Current price: N/A")
    print(f"Grid center: ${grid_center_price:.{PRICE_DECIMALS}f}")
    print(f"Position: {position['size']:+.{SIZE_DECIMALS}f} (${position['position_value']:+,.2f})")
    print(f"Unrealized PnL: ${position['unrealized_pnl']:+,.2f}")
    print(f"Account value: ${account_info['account_value']:,.2f}")
    print(f"Active grid orders: {len(level_orders)}")
    print(f"Completed round trips: {completed_round_trips}")
    print(f"Total grid profit: ${total_grid_profit:+,.4f}")
    print(f"{'='*60}\n")


def main():
    """Main grid trading loop"""
    global ws_client, emergency_stop, paused

    # Handle SIGTERM (sent by process.terminate()) gracefully
    # This converts SIGTERM to KeyboardInterrupt so cleanup code runs
    def handle_sigterm(signum, frame):
        print("\nReceived SIGTERM signal...")
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, handle_sigterm)

    print(f"\n{'#'*60}")
    print(f"# GRID TRADING BOT - {MARKET_DISPLAY}")
    print(f"{'#'*60}")
    print(f"Grid spacing: {GRID_SPACING_PCT}%")
    print(f"Levels per side: {NUM_LEVELS_EACH_SIDE}")
    print(f"Order size: ${ORDER_SIZE_USD}")
    print(f"Bias: {BIAS}")
    print(f"Max position: ${MAX_POSITION_USD}")
    print(f"Leverage: {LEVERAGE}x")
    print(f"Emergency stop loss: {EMERGENCY_STOP_LOSS_PCT}%")
    print(f"Max account drawdown: {MAX_ACCOUNT_DRAWDOWN_PCT}%")
    print(f"Close position on emergency: {CLOSE_POSITION_ON_EMERGENCY}")
    print(f"{'#'*60}\n")

    # Set leverage
    set_leverage()
    print()

    # Initialize WebSocket
    print("Initializing WebSocket connection...")
    try:
        ws_client = MarketDataWebSocket(
            spot_coin=MARKET_NAME,  # e.g., "xyz:COPPER" for HIP-3 markets
            account_address=account_address,
            pair_name=MARKET_NAME,
            update_threshold_bps=10.0,  # Less sensitive for grid trading
            on_update_callback=lambda x: None
        )
        ws_client.start()
        print("WebSocket connected\n")
    except Exception as e:
        print(f"WebSocket failed: {e}")
        print("Continuing with REST API polling\n")
        ws_client = None

    # Start metrics capture
    print("Starting metrics capture...")
    metrics_capture = MetricsCapture(MARKET_DISPLAY, get_bot_state_for_metrics)
    metrics_capture.start()
    print()

    # Get initial price and initialize grid
    current_price = get_mark_price()
    if not current_price:
        print("ERROR: Could not get initial price. Exiting.")
        return

    initialize_grid(current_price)

    # Record starting account value for drawdown calculation
    global starting_account_value
    account_info = get_account_value()
    starting_account_value = account_info['account_value']
    print(f"\nStarting account value: ${starting_account_value:,.2f}")
    print(f"Max drawdown trigger: ${starting_account_value * (1 + MAX_ACCOUNT_DRAWDOWN_PCT/100):,.2f} ({MAX_ACCOUNT_DRAWDOWN_PCT}%)\n")

    # Main loop
    iteration = 0
    last_status_print = 0
    last_sync = 0

    try:
        while not emergency_stop:
            iteration += 1
            now = time.time()

            # Check for fills - WebSocket or REST depending on market type
            if ws_client:
                new_fills = ws_client.get_new_fills()
            else:
                # REST polling for HIP-3 markets
                new_fills = check_fills_rest()

            for fill in new_fills:
                handle_fill(fill)
                record_fill_to_db(fill)

            # Periodic sync with exchange (every 30s)
            if now - last_sync > 30:
                sync_grid_with_exchange()
                last_sync = now

                # Check WebSocket health and reconnect if needed
                if ws_client and not ws_client.is_healthy():
                    print("\nWebSocket unhealthy, attempting reconnect...")
                    if ws_client.reconnect():
                        print("WebSocket reconnected!")
                    else:
                        print("WebSocket reconnect failed, continuing with REST")

                # Refill any missing grid orders
                current_price = get_mark_price()
                if current_price:
                    # Check if rebalance needed
                    if check_grid_rebalance(current_price):
                        print("Rebalancing grid...")
                        initialize_grid(current_price)
                    else:
                        # Just fill in any gaps
                        place_grid_orders(current_price)

            # Print status periodically (every 60s)
            if now - last_status_print > HEALTH_CHECK_SECONDS:
                print_status()
                last_status_print = now

            # Safety checks
            position = get_position()
            account_info = get_account_value()

            # Emergency stop loss (based on unrealized PnL)
            if position['unrealized_pnl'] < 0:
                loss_pct = (position['unrealized_pnl'] / account_info['account_value']) * 100 if account_info['account_value'] > 0 else 0
                if loss_pct < EMERGENCY_STOP_LOSS_PCT:
                    print(f"\n{'!'*60}")
                    print(f"EMERGENCY STOP: Unrealized loss {loss_pct:.2f}% exceeds threshold {EMERGENCY_STOP_LOSS_PCT}%")
                    print(f"{'!'*60}")
                    emergency_stop = True
                    break

            # Account drawdown check (from session start)
            if starting_account_value > 0 and account_info['account_value'] > 0:
                drawdown_pct = ((account_info['account_value'] - starting_account_value) / starting_account_value) * 100
                if drawdown_pct < MAX_ACCOUNT_DRAWDOWN_PCT:
                    print(f"\n{'!'*60}")
                    print(f"EMERGENCY STOP: Account drawdown {drawdown_pct:.2f}% exceeds threshold {MAX_ACCOUNT_DRAWDOWN_PCT}%")
                    print(f"Started at: ${starting_account_value:,.2f}, Now: ${account_info['account_value']:,.2f}")
                    print(f"{'!'*60}")
                    emergency_stop = True
                    break

            # Margin check
            if account_info['margin_ratio_pct'] < MIN_MARGIN_RATIO_PCT and account_info['margin_ratio_pct'] > 0:
                print(f"\nWARNING: Margin ratio {account_info['margin_ratio_pct']:.1f}% below minimum {MIN_MARGIN_RATIO_PCT}%")

            # Sleep between iterations
            time.sleep(FILL_CHECK_SECONDS)

    except KeyboardInterrupt:
        print("\n\nShutting down grid bot...")

    finally:
        # Cleanup
        print("\nCancelling all orders...")
        cancel_all_orders()

        # Close position if emergency stop triggered and configured to do so
        if emergency_stop and CLOSE_POSITION_ON_EMERGENCY:
            print("\nClosing position due to emergency stop...")
            close_position()

        if ws_client:
            ws_client.stop()

        if metrics_capture:
            metrics_capture.stop()

        print_status()

        if emergency_stop:
            print(f"\n{'!'*60}")
            print("BOT STOPPED DUE TO EMERGENCY - CHECK YOUR POSITION")
            print(f"{'!'*60}")
        else:
            print("Grid bot stopped normally")


if __name__ == "__main__":
    main()
