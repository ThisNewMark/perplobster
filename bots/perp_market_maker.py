#!/usr/bin/env python3
"""
Generic Perpetual Market Maker with Event-Driven Architecture
Loads configuration from specified config file

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

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from parameter_manager import ParameterManager
from metrics_capture import MetricsCapture
from config_loader import ConfigLoader
from websocket_integration import MarketDataWebSocket
from credentials import get_builder, ensure_builder_fee_approved

# ============================================================
# PARSE COMMAND LINE ARGUMENTS
# ============================================================

parser = argparse.ArgumentParser(description='Generic perpetual market maker bot')
parser.add_argument('--config', required=True, help='Path to config file (e.g., config/icp_perp_config.json)')
args = parser.parse_args()

# ============================================================
# CONFIGURATION - LOAD FROM FILE
# ============================================================

print(f"📂 Loading configuration from {args.config}...")
CONFIG = ConfigLoader.load(args.config)
ConfigLoader.validate_trading_config(CONFIG)
print("✅ Configuration loaded and validated")

# Extract pair info from config
MARKET_NAME = CONFIG['market']  # e.g., "ICP", "ETH", "BTC", or "xyz:COPPER" for HIP-3
DEX = CONFIG.get('dex', '')  # e.g., "xyz", "flx", or "" for canonical markets
IS_HIP3_MARKET = DEX != ''  # HIP-3 builder markets need special handling
MARKET_DISPLAY = f"{MARKET_NAME}-PERP"  # For display purposes

# Market making settings from config
BASE_ORDER_SIZE = CONFIG['trading']['base_order_size']  # In USD notional
MIN_ORDER_SIZE = CONFIG['trading']['min_order_size']
SIZE_INCREMENT = CONFIG['trading'].get('size_increment', 0.001)  # For contract size rounding

BASE_SPREAD_BPS = CONFIG['trading']['base_spread_bps']
MIN_SPREAD_BPS = CONFIG['trading']['min_spread_bps']
MAX_SPREAD_BPS = CONFIG['trading']['max_spread_bps']

# Position management (in USD notional, can be positive/negative)
TARGET_POSITION_USD = CONFIG['position']['target_position_usd']  # 0 = delta neutral
MAX_POSITION_USD = CONFIG['position']['max_position_usd']  # Maximum absolute notional
LEVERAGE = CONFIG['position'].get('leverage', 5)  # Leverage multiplier

# Inventory skew parameters
INVENTORY_SKEW_THRESHOLD_USD = CONFIG['inventory'].get('inventory_skew_threshold_usd', 0)
INVENTORY_SKEW_BPS_PER_1K = CONFIG['inventory']['inventory_skew_bps_per_1k']  # Per $1000 deviation
MAX_SKEW_BPS = CONFIG['inventory'].get('max_skew_bps', 500)

# Funding rate parameters
MAX_FUNDING_RATE_PCT_8H = CONFIG['funding'].get('max_funding_rate_pct_8h', 0.5)  # Stop if funding >0.5% per 8h
FUNDING_SKEW_MULTIPLIER = CONFIG['funding'].get('funding_skew_multiplier', 100)  # Skew 100 bps per 0.01% funding

# Profit-taking parameters
PROFIT_TAKE_THRESHOLD_USD = CONFIG.get('profit_taking', {}).get('threshold_usd', 10.0)  # Start taking profit at $10 unrealized PnL
PROFIT_TAKE_AGGRESSION_BPS = CONFIG.get('profit_taking', {}).get('aggression_bps', 15.0)  # Tighten spread by 15 bps when profitable

# Timing
UPDATE_THRESHOLD_BPS = CONFIG['timing']['update_threshold_bps']
FALLBACK_CHECK_SECONDS = CONFIG['timing'].get('fallback_check_seconds', 30)

# Safety
MAX_QUOTE_COUNT = CONFIG['safety']['max_quote_count']
EMERGENCY_STOP_LOSS_PCT = CONFIG['safety']['emergency_stop_loss_pct']
SMART_ORDER_MGMT_ENABLED = CONFIG['safety']['smart_order_mgmt_enabled']
MIN_MARGIN_RATIO_PCT = CONFIG['safety'].get('min_margin_ratio_pct', 10.0)  # Close position if margin <10%

# Exchange config
PRICE_DECIMALS = CONFIG['exchange'].get('price_decimals', 2)
SIZE_DECIMALS = CONFIG['exchange'].get('size_decimals', 4)

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
main_address = credentials.get("account_address", "")
account = Account.from_key(secret_key)
account_address = SUBACCOUNT_ADDRESS if IS_SUBACCOUNT else main_address or account.address

print(f"🔑 Trading account: {account_address}")
if IS_SUBACCOUNT:
    print(f"   (Subaccount of {main_address or account.address})")
if IS_HIP3_MARKET:
    print(f"📦 HIP-3 market detected: {MARKET_NAME} on {DEX}")

# Setup Hyperliquid API with HIP-3 support
base_url = constants.MAINNET_API_URL
perp_dexs = ["", "xyz", "flx"] if IS_HIP3_MARKET else None

info = Info(base_url=base_url, skip_ws=True, perp_dexs=perp_dexs) if IS_HIP3_MARKET else Info(base_url, skip_ws=True)

# Create Exchange - for subaccounts, wallet signs with main account but vault_address specifies subaccount
exchange = Exchange(
    wallet=account,
    base_url=base_url,
    account_address=main_address or None,
    vault_address=SUBACCOUNT_ADDRESS if IS_SUBACCOUNT else None,
    perp_dexs=perp_dexs
) if IS_HIP3_MARKET else Exchange(
    wallet=account,
    base_url=base_url,
    account_address=main_address or None,
    vault_address=SUBACCOUNT_ADDRESS if IS_SUBACCOUNT else None
)

# Auto-approve builder fee on first run (one-time, supports Perp Lobster development)
ensure_builder_fee_approved(exchange)

# ============================================================
# DATABASE SETUP
# ============================================================

# Parameter manager tracks config changes (uses global trading_data.db)
param_manager = ParameterManager(MARKET_DISPLAY)  # e.g., "ICP-PERP"

# ============================================================
# GLOBAL STATE
# ============================================================

last_mark_price = None
last_position_usd = None
cached_market_info = None  # Cache market metadata
last_info_fetch = 0
INFO_CACHE_SECONDS = 5.0

emergency_stop = False
rate_limit_hit = False
consecutive_connection_failures = 0

# Smart order management state
current_bid_oid = None
current_ask_oid = None
current_bid_price = None
current_ask_price = None
current_bid_size = None
current_ask_size = None

# Volatility circuit breaker state
price_history = []  # List of (timestamp, price) tuples
circuit_breaker_active = False
circuit_breaker_activated_at = None
last_volatility_check = 0

# WebSocket client
ws_client = None
use_websocket = True  # Always use WebSocket for perps

# Metrics capture
metrics_capture = None

# ============================================================
# MARKET DATA FUNCTIONS
# ============================================================

def get_market_info():
    """Fetch market metadata (cached for 5s)"""
    global cached_market_info, last_info_fetch

    now = time.time()
    if cached_market_info and (now - last_info_fetch) < INFO_CACHE_SECONDS:
        return cached_market_info

    try:
        # For HIP-3 markets, need to include perp_dexs in the API call
        if IS_HIP3_MARKET:
            result = info.post("/info", {"type": "metaAndAssetCtxs", "perp_dexs": ["", "xyz", "flx"]})
            meta = result[0] if isinstance(result, list) else result
        else:
            meta = info.meta()

        universe = meta.get('universe', [])

        # Find our market in the universe
        market_info = next((m for m in universe if m['name'] == MARKET_NAME), None)

        if not market_info:
            # Don't warn every time, just return None - the bot still works without this metadata
            return None

        cached_market_info = market_info
        last_info_fetch = now
        return market_info

    except Exception as e:
        print(f"⚠️  Error fetching market info: {e}")
        return None

def get_mark_price():
    """Get current mark price for the perp"""
    try:
        # Use WebSocket data if available
        if use_websocket and ws_client:
            orderbook = ws_client.get_orderbook()
            if orderbook:
                return orderbook['mid']

        # Fallback to REST API
        l2_data = info.l2_snapshot(MARKET_NAME)

        if not l2_data or 'levels' not in l2_data:
            return None

        levels = l2_data['levels']
        if len(levels) < 2 or not levels[0] or not levels[1]:
            return None

        bids = levels[0]
        asks = levels[1]

        if not bids or not asks:
            return None

        best_bid = float(bids[0]['px'])
        best_ask = float(asks[0]['px'])
        mid = (best_bid + best_ask) / 2

        return mid

    except Exception as e:
        print(f"⚠️  Error fetching mark price: {e}")
        return None

def get_funding_rate():
    """Get current funding rate (returns rate per 8 hours)"""
    try:
        market_info = get_market_info()
        if not market_info:
            return 0.0

        funding_str = market_info.get('funding', '0.0')
        return float(funding_str)

    except Exception as e:
        print(f"⚠️  Error fetching funding rate: {e}")
        return 0.0

def get_position():
    """Get current position for this perp market

    Returns: {
        'size': float (signed size, positive = long, negative = short),
        'entry_px': float,
        'position_value': float (USD notional),
        'unrealized_pnl': float,
        'leverage': float,
        'liquidation_px': float or None
    }
    """
    try:
        user_state = info.user_state(account_address, dex=DEX) if IS_HIP3_MARKET else info.user_state(account_address)
        asset_positions = user_state.get('assetPositions', [])

        # Find our market's position
        perp_position = next(
            (p for p in asset_positions if p['position']['coin'] == MARKET_NAME),
            None
        )

        if not perp_position:
            # No position
            return {
                'size': 0.0,
                'entry_px': 0.0,
                'position_value': 0.0,
                'unrealized_pnl': 0.0,
                'leverage': 0.0,
                'liquidation_px': None
            }

        pos_data = perp_position['position']

        size = float(pos_data.get('szi', 0.0))
        entry_px = float(pos_data.get('entryPx', 0.0)) if size != 0 else 0.0
        position_value = float(pos_data.get('positionValue', 0.0))

        # CRITICAL: API returns position_value as unsigned (always positive)
        # Make it signed based on position direction (size < 0 = short = negative value)
        position_value = position_value if size >= 0 else -position_value

        unrealized_pnl = float(pos_data.get('unrealizedPnl', 0.0))
        leverage_str = pos_data.get('leverage', {}).get('value', '0')
        leverage = float(leverage_str) if leverage_str != 'cross' else 0.0
        liquidation_px = pos_data.get('liquidationPx')

        return {
            'size': size,
            'entry_px': entry_px,
            'position_value': position_value,
            'unrealized_pnl': unrealized_pnl,
            'leverage': leverage,
            'liquidation_px': float(liquidation_px) if liquidation_px else None
        }

    except Exception as e:
        print(f"⚠️  Error fetching position: {e}")
        return {
            'size': 0.0,
            'entry_px': 0.0,
            'position_value': 0.0,
            'unrealized_pnl': 0.0,
            'leverage': 0.0,
            'liquidation_px': None
        }

def get_account_value():
    """Get account value and margin info"""
    try:
        user_state = info.user_state(account_address, dex=DEX) if IS_HIP3_MARKET else info.user_state(account_address)
        margin_summary = user_state.get('marginSummary', {})

        account_value = float(margin_summary.get('accountValue', 0.0))
        total_margin_used = float(margin_summary.get('totalMarginUsed', 0.0))
        total_ntl_pos = float(margin_summary.get('totalNtlPos', 0.0))  # Total notional position

        # Calculate margin ratio (account_value / margin_used)
        margin_ratio_pct = (account_value / total_margin_used * 100) if total_margin_used > 0 else 0

        return {
            'account_value': account_value,
            'total_margin_used': total_margin_used,
            'total_ntl_pos': total_ntl_pos,
            'margin_ratio_pct': margin_ratio_pct
        }

    except Exception as e:
        print(f"⚠️  Error fetching account value: {e}")
        return {
            'account_value': 0.0,
            'total_margin_used': 0.0,
            'total_ntl_pos': 0.0,
            'margin_ratio_pct': 0.0
        }

# ============================================================
# ORDER MANAGEMENT
# ============================================================

def cancel_all_orders():
    """Cancel all open orders for this market"""
    try:
        open_orders = info.open_orders(account_address, dex=DEX) if IS_HIP3_MARKET else info.open_orders(account_address)
        market_orders = [o for o in open_orders if o.get('coin') == MARKET_NAME]

        if not market_orders:
            return 0

        for order in market_orders:
            oid = order.get('oid')
            try:
                exchange.cancel(MARKET_NAME, oid)
                print(f"   Cancelled order {oid}")
            except Exception as e:
                print(f"   ⚠️  Error cancelling {oid}: {e}")

        return len(market_orders)

    except Exception as e:
        print(f"   ⚠️  Error cancelling orders: {e}")
        return 0

def place_quote(is_buy, price, size_contracts):
    """Place a perp limit order (maker-only)

    Args:
        is_buy: True for bid, False for ask
        price: Limit price
        size_contracts: Size in contracts (will be converted to proper decimal format)

    Returns: (success: bool, order_id: str or None)
    """
    global rate_limit_hit

    try:
        # Round price to configured decimal places
        price = round(price, PRICE_DECIMALS)

        # Round size to configured decimals
        size_contracts = round(size_contracts, SIZE_DECIMALS)

        # Enforce minimum size
        if size_contracts < MIN_ORDER_SIZE:
            return False, None

        # Use post-only orders to ensure maker rebates (ALO = Add Liquidity Only)
        order_type = {"limit": {"tif": "Alo"}}

        # Place perp order
        result = exchange.order(
            MARKET_NAME,      # coin
            is_buy,           # is_buy
            size_contracts,   # sz
            price,            # limit_px
            order_type,       # order_type
            False,            # reduce_only
            builder=get_builder()
        )

        # Check if order was successful
        if result.get("status") == "ok":
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            if statuses and "resting" in statuses[0]:
                # Extract order ID from resting status
                resting_info = statuses[0].get("resting", {})
                oid = resting_info.get("oid")
                return True, oid
            elif statuses and "error" in statuses[0]:
                error_msg = statuses[0].get("error", "Unknown error")
                print(f"      ❌ Order error: {error_msg}")
                return False, None
            else:
                # Status OK but no resting or error - unexpected state
                print(f"      ⚠️  Order response unexpected: {statuses}")
                return False, None
        else:
            # Status not OK - log full response
            response_text = str(result.get('response', ''))
            print(f"      ❌ Order failed: {result.get('status', 'unknown status')}")
            print(f"         Full response: {result}")

            # Check for rate limit error
            if 'Too many cumulative requests' in response_text or 'cumulative volume traded' in response_text:
                print(f"\n{'='*80}")
                print(f"🛑 RATE LIMIT DETECTED - STOPPING BOT")
                print(f"{'='*80}")
                print(f"Hyperliquid has blocked further orders due to insufficient trading volume.")
                print(f"To resume trading, you must place taker orders to build volume:")
                print(f"  • Every $1 traded = 1 more request allowed")
                print(f"  • You likely need $2000-3000 in volume to unlock enough quota")
                print(f"\nBot will now stop to avoid wasting remaining quota.")
                print(f"{'='*80}\n")
                rate_limit_hit = True

            return False, None
    except Exception as e:
        print(f"   ⚠️  Error placing {'buy' if is_buy else 'sell'} order: {e}")
        return False, None

def get_current_orders():
    """Get current open orders for this perp market

    Returns: {'bid': order_dict or None, 'ask': order_dict or None}
    """
    try:
        open_orders = info.open_orders(account_address, dex=DEX) if IS_HIP3_MARKET else info.open_orders(account_address)
        market_orders = [o for o in open_orders if o.get('coin') == MARKET_NAME]

        bid_order = None
        ask_order = None

        for order in market_orders:
            if order.get('side') == 'B':  # Buy
                bid_order = order
            elif order.get('side') == 'A':  # Ask/Sell
                ask_order = order

        return {'bid': bid_order, 'ask': ask_order}
    except Exception as e:
        print(f"   ⚠️  Error fetching current orders: {e}")
        return {'bid': None, 'ask': None}

def cancel_specific_orders(bid_oid=None, ask_oid=None):
    """Cancel specific orders by OID

    Returns: (bid_cancelled: bool, ask_cancelled: bool)
    """
    bid_cancelled = False
    ask_cancelled = False

    try:
        if bid_oid:
            try:
                exchange.cancel(MARKET_NAME, bid_oid)
                bid_cancelled = True
                print(f"   Cancelled bid {bid_oid}")
            except Exception as e:
                print(f"   ⚠️  Error canceling bid: {e}")

        if ask_oid:
            try:
                exchange.cancel(MARKET_NAME, ask_oid)
                ask_cancelled = True
                print(f"   Cancelled ask {ask_oid}")
            except Exception as e:
                print(f"   ⚠️  Error canceling ask: {e}")

        return bid_cancelled, ask_cancelled

    except Exception as e:
        print(f"   ⚠️  Error in cancel_specific_orders: {e}")
        return bid_cancelled, ask_cancelled

# ============================================================
# PRICING LOGIC
# ============================================================

def calculate_skewed_mid(mark_price, position_usd, funding_rate):
    """Calculate skewed mid price based on position and funding

    Args:
        mark_price: Current mark price
        position_usd: Current position in USD (positive = long, negative = short)
        funding_rate: Current funding rate per 8h

    Returns:
        skewed_mid: Adjusted mid price
    """
    skewed_mid = mark_price

    # 1. Position-based skew (inventory management)
    position_deviation = position_usd - TARGET_POSITION_USD

    # Apply threshold (dead zone)
    if abs(position_deviation) > INVENTORY_SKEW_THRESHOLD_USD:
        # Calculate skew in bps
        deviation_beyond_threshold = position_deviation - (
            INVENTORY_SKEW_THRESHOLD_USD if position_deviation > 0 else -INVENTORY_SKEW_THRESHOLD_USD
        )

        # Skew per $1000 deviation
        inventory_skew_bps = (deviation_beyond_threshold / 1000) * INVENTORY_SKEW_BPS_PER_1K

        # Cap the skew
        if abs(inventory_skew_bps) > MAX_SKEW_BPS:
            inventory_skew_bps = MAX_SKEW_BPS if inventory_skew_bps > 0 else -MAX_SKEW_BPS

        # Apply to mid (if long, skew mid down to encourage selling)
        skew_multiplier = 1 - (inventory_skew_bps / 10000)
        skewed_mid *= skew_multiplier

        print(f"   Position skew: {position_deviation:+.2f} USD → {inventory_skew_bps:+.1f} bps adjustment")

    # 2. Funding rate skew (avoid paying funding)
    # If funding is positive (longs pay shorts), we want to lean short
    # If funding is negative (shorts pay longs), we want to lean long
    funding_skew_bps = funding_rate * 100 * FUNDING_SKEW_MULTIPLIER

    if abs(funding_skew_bps) > 10:  # Only log if significant (>10 bps)
        print(f"   Funding skew: {funding_rate:.4f}% → {funding_skew_bps:+.1f} bps adjustment")
        funding_multiplier = 1 - (funding_skew_bps / 10000)
        skewed_mid *= funding_multiplier

    return skewed_mid

# ============================================================
# VOLATILITY CIRCUIT BREAKER
# ============================================================

def update_price_history(current_price):
    """Track price history for volatility monitoring"""
    global price_history

    now = time.time()
    price_history.append((now, current_price))

    # Keep only last 15 minutes of data
    cutoff_time = now - (15 * 60)
    price_history = [(t, p) for t, p in price_history if t > cutoff_time]

def check_volatility():
    """
    Check if market volatility exceeds safety thresholds

    Returns: (should_pause, volatility_pct, time_window)
    """
    global price_history, circuit_breaker_active, circuit_breaker_activated_at

    if len(price_history) < 2:
        return False, 0, 0

    now = time.time()

    # Check 10-minute volatility (pause threshold)
    ten_min_ago = now - (10 * 60)
    recent_prices = [(t, p) for t, p in price_history if t > ten_min_ago]

    if len(recent_prices) >= 2:
        prices = [p for _, p in recent_prices]
        min_price = min(prices)
        max_price = max(prices)
        volatility_10min = ((max_price - min_price) / min_price) * 100

        # PAUSE if volatility > 5% in 10 minutes
        if volatility_10min > 5.0:
            if not circuit_breaker_active:
                circuit_breaker_active = True
                circuit_breaker_activated_at = now
                print(f"\n🚨 CIRCUIT BREAKER ACTIVATED!")
                print(f"   Volatility: {volatility_10min:.2f}% over 10 minutes")
                print(f"   Pausing trading until market calms down...")
                # Cancel all orders when circuit breaker activates
                try:
                    cancel_all_orders()
                except Exception as e:
                    print(f"   ⚠️  Could not cancel orders: {e}")
            return True, volatility_10min, 10

    # Check if we should RESUME (only if currently paused)
    if circuit_breaker_active:
        # Need 15 minutes of calm (< 2% moves) to resume
        fifteen_min_ago = now - (15 * 60)
        calm_period_prices = [(t, p) for t, p in price_history if t > fifteen_min_ago]

        if len(calm_period_prices) >= 2:
            prices = [p for _, p in calm_period_prices]
            min_price = min(prices)
            max_price = max(prices)
            volatility_15min = ((max_price - min_price) / min_price) * 100

            # RESUME if volatility < 2% over 15 minutes
            if volatility_15min < 2.0:
                pause_duration = (now - circuit_breaker_activated_at) / 60
                print(f"\n✅ CIRCUIT BREAKER DEACTIVATED")
                print(f"   Market volatility normalized: {volatility_15min:.2f}% over 15 minutes")
                print(f"   Paused for {pause_duration:.1f} minutes")
                print(f"   Resuming trading...")
                circuit_breaker_active = False
                circuit_breaker_activated_at = None
                return False, volatility_15min, 15
            else:
                # Still too volatile, remain paused
                return True, volatility_15min, 15

    return False, 0, 0

def update_quotes():
    """Main quote update logic"""
    global last_mark_price, last_position_usd
    global current_bid_oid, current_ask_oid, current_bid_price, current_ask_price
    global current_bid_size, current_ask_size

    print(f"\n{'='*80}")
    print(f"UPDATE QUOTES - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*80}")

    # Check emergency stop
    if emergency_stop:
        print("🛑 Emergency stop triggered - cancelling all orders")
        cancel_all_orders()
        return

    # Get market data
    mark_price = get_mark_price()
    if not mark_price:
        print("⚠️  Failed to fetch mark price, skipping update")
        return

    # Update price history for volatility monitoring
    update_price_history(mark_price)

    # Get position
    position = get_position()
    position_usd = position['position_value']
    position_size = position['size']
    unrealized_pnl = position['unrealized_pnl']

    # Get account info
    account_info = get_account_value()
    margin_ratio = account_info['margin_ratio_pct']

    # Get funding rate
    funding_rate = get_funding_rate()

    print(f"📊 Market: {MARKET_DISPLAY}")
    print(f"   Mark price: ${mark_price:.{PRICE_DECIMALS}f}")
    print(f"   Position: {position_size:+.{SIZE_DECIMALS}f} contracts (${position_usd:+,.2f})")
    print(f"   Target: ${TARGET_POSITION_USD:,.2f} | Max: ${MAX_POSITION_USD:,.2f}")
    print(f"   Unrealized PnL: ${unrealized_pnl:+,.2f}")
    print(f"   Account value: ${account_info['account_value']:,.2f}")
    print(f"   Margin ratio: {margin_ratio:.1f}%")
    print(f"   Funding: {funding_rate:.4f}% per 8h")

    # Safety checks
    if margin_ratio < MIN_MARGIN_RATIO_PCT and margin_ratio > 0:
        print(f"\n⚠️  MARGIN RATIO LOW: {margin_ratio:.1f}% < {MIN_MARGIN_RATIO_PCT}%")
        print("   Consider reducing position or adding margin!")

    if abs(funding_rate) > MAX_FUNDING_RATE_PCT_8H:
        print(f"\n⚠️  FUNDING RATE HIGH: {abs(funding_rate):.4f}% > {MAX_FUNDING_RATE_PCT_8H}%")
        print("   Stopping quoting to avoid funding costs")
        cancel_all_orders()
        return

    # Check position limits
    if abs(position_usd) > MAX_POSITION_USD:
        print(f"\n⚠️  POSITION LIMIT EXCEEDED: ${abs(position_usd):,.2f} > ${MAX_POSITION_USD:,.2f}")

        # Calculate how much to reduce
        excess_usd = abs(position_usd) - MAX_POSITION_USD

        # Check if margin is also tight (ratio > 100%)
        margin_tight = margin_ratio > 100.0

        if margin_tight:
            print(f"   ⚠️  MARGIN ALSO TIGHT: {margin_ratio:.1f}%")
            print(f"   Using MARKET ORDER to immediately reduce position by ${excess_usd:.2f}")

            # Use market order to immediately reduce position
            # Calculate size needed to reduce to max limit
            reduce_size_contracts = (excess_usd + 50) / mark_price  # Add $50 buffer to get under limit
            reduce_size_contracts = round(reduce_size_contracts, SIZE_DECIMALS)

            cancel_all_orders()

            try:
                # Determine direction based on SIGNED position size, not unsigned position_usd
                # position_size is negative for shorts, positive for longs
                is_buy = position_size < 0  # If short (negative), buy to close; if long (positive), sell to close

                # Place market order using IOC (Immediate or Cancel) with extreme price
                # Market orders are effectively "limit orders" at extreme prices that will fill immediately
                if is_buy:
                    # Buy market order (use very high limit price - 5% above market)
                    extreme_price = mark_price * 1.05
                    extreme_price = round(extreme_price, PRICE_DECIMALS)
                    print(f"   Placing MARKET BUY for {reduce_size_contracts} contracts at ${extreme_price}...")
                    result = exchange.order(
                        MARKET_NAME,              # coin
                        True,                      # is_buy
                        reduce_size_contracts,    # sz
                        extreme_price,            # limit_px
                        {"limit": {"tif": "Ioc"}},  # order_type: IOC = fill immediately
                        True,                      # reduce_only
                        builder=get_builder()
                    )
                else:
                    # Sell market order (use very low limit price - 5% below market)
                    extreme_price = mark_price * 0.95
                    extreme_price = round(extreme_price, PRICE_DECIMALS)
                    print(f"   Placing MARKET SELL for {reduce_size_contracts} contracts at ${extreme_price}...")
                    result = exchange.order(
                        MARKET_NAME,              # coin
                        False,                     # is_buy
                        reduce_size_contracts,    # sz
                        extreme_price,            # limit_px
                        {"limit": {"tif": "Ioc"}},  # order_type: IOC = fill immediately
                        True,                      # reduce_only
                        builder=get_builder()
                    )

                print(f"   ✅ Market order executed: {result}")
                print(f"   Position should be reduced on next iteration")

            except Exception as e:
                print(f"   ❌ Market order failed: {e}")
                print(f"   Will retry on next iteration")

            return
        else:
            # Margin OK, just use limit orders on reducing side
            print("   Only quoting on side that reduces position")

            # Calculate safe order size based on available margin
            account_value = account_info['account_value']
            margin_used = abs(position_usd) / LEVERAGE
            free_margin = account_value - margin_used

            # Use 80% of free margin for the reducing order
            safe_order_usd = free_margin * 0.8 * LEVERAGE
            safe_order_usd = min(safe_order_usd, abs(position_usd) / 2)  # Max half position
            size_contracts = safe_order_usd / mark_price
            size_contracts = round(size_contracts, SIZE_DECIMALS)

            print(f"   Free margin: ${free_margin:.2f} → Order size: {size_contracts} contracts")

            # Quote only on reducing side
            if position_size > 0:  # Long, only allow selling
                cancel_all_orders()
                # Place only ask order
                spread_half = BASE_SPREAD_BPS / 2
                ask_price = mark_price * (1 + spread_half / 10000)
                ask_price = round(ask_price, PRICE_DECIMALS)
                place_quote(False, ask_price, size_contracts)
            else:  # Short, only allow buying
                cancel_all_orders()
                # Place only bid order
                spread_half = BASE_SPREAD_BPS / 2
                bid_price = mark_price * (1 - spread_half / 10000)
                bid_price = round(bid_price, PRICE_DECIMALS)
                place_quote(True, bid_price, size_contracts)

            return

    # Calculate skewed mid
    skewed_mid = calculate_skewed_mid(mark_price, position_usd, funding_rate)

    # Calculate spread
    spread_bps = BASE_SPREAD_BPS
    spread_bps = max(spread_bps, MIN_SPREAD_BPS)
    spread_bps = min(spread_bps, MAX_SPREAD_BPS)

    spread_half = spread_bps / 2

    # Profit-taking logic: Tighten spread on reducing side when position is profitable
    bid_spread_half = spread_half
    ask_spread_half = spread_half

    if abs(unrealized_pnl) > PROFIT_TAKE_THRESHOLD_USD:
        if position_size > 0 and unrealized_pnl > 0:
            # Long and profitable → tighten ask to encourage selling
            ask_spread_half = max(1.0, spread_half - PROFIT_TAKE_AGGRESSION_BPS)
            print(f"   💰 PROFIT TAKING: Long ${unrealized_pnl:+.2f} → Tightening ask by {PROFIT_TAKE_AGGRESSION_BPS:.1f}bps")
        elif position_size < 0 and unrealized_pnl > 0:
            # Short and profitable → tighten bid to encourage buying
            bid_spread_half = max(1.0, spread_half - PROFIT_TAKE_AGGRESSION_BPS)
            print(f"   💰 PROFIT TAKING: Short ${unrealized_pnl:+.2f} → Tightening bid by {PROFIT_TAKE_AGGRESSION_BPS:.1f}bps")

    # Calculate bid/ask prices with profit-taking adjustment
    target_bid = skewed_mid * (1 - bid_spread_half / 10000)
    target_ask = skewed_mid * (1 + ask_spread_half / 10000)

    # Round to valid precision
    target_bid = round(target_bid, PRICE_DECIMALS)
    target_ask = round(target_ask, PRICE_DECIMALS)

    # Calculate order sizes in contracts
    # BASE_ORDER_SIZE is in USD, convert to contracts
    bid_size_contracts = BASE_ORDER_SIZE / mark_price
    ask_size_contracts = BASE_ORDER_SIZE / mark_price

    # Round to valid decimals
    bid_size_contracts = round(bid_size_contracts, SIZE_DECIMALS)
    ask_size_contracts = round(ask_size_contracts, SIZE_DECIMALS)

    # Get current best bid/ask to prevent crossing spread (post-only rejection)
    current_best_bid = None
    current_best_ask = None

    if use_websocket and ws_client:
        orderbook = ws_client.get_orderbook()
        if orderbook:
            current_best_bid = orderbook.get('best_bid')
            current_best_ask = orderbook.get('best_ask')

    # Adjust quotes to not cross spread (post-only orders can't cross)
    if current_best_bid and target_bid >= current_best_bid:
        # Our bid would cross spread → adjust to just below best bid
        original_bid = target_bid
        target_bid = current_best_bid - (1 / (10 ** PRICE_DECIMALS))  # One tick below
        target_bid = round(target_bid, PRICE_DECIMALS)
        print(f"   ⚠️  Adjusted bid from ${original_bid:.{PRICE_DECIMALS}f} to ${target_bid:.{PRICE_DECIMALS}f} (would cross spread)")

    if current_best_ask and target_ask <= current_best_ask:
        # Our ask would cross spread → adjust to just above best ask
        original_ask = target_ask
        target_ask = current_best_ask + (1 / (10 ** PRICE_DECIMALS))  # One tick above
        target_ask = round(target_ask, PRICE_DECIMALS)
        print(f"   ⚠️  Adjusted ask from ${original_ask:.{PRICE_DECIMALS}f} to ${target_ask:.{PRICE_DECIMALS}f} (would cross spread)")

    # Position limit prevention: Don't place orders that would exceed max position
    # Calculate what position would be after fills
    bid_size_usd = bid_size_contracts * mark_price
    ask_size_usd = ask_size_contracts * mark_price

    allow_bid = True  # BUY order increases long / decreases short
    allow_ask = True  # SELL order decreases long / increases short

    # Position limit prevention logic
    # CRITICAL: Only block orders that INCREASE position, always allow reducing orders
    # Use position_size (signed) to determine long vs short, NOT position_usd (always positive)

    if position_size > 0:  # Currently LONG (positive size)
        # BID (buy) would increase long → check limit
        if (position_usd + bid_size_usd) > MAX_POSITION_USD * 0.9:
            allow_bid = False
            print(f"   ⚠️  Skipping BID: would increase long position beyond limit")
        # ASK (sell) would decrease long → always allow (reducing)

    elif position_size < 0:  # Currently SHORT (negative size)
        # ASK (sell) would increase short → check limit
        if (abs(position_usd) + ask_size_usd) > MAX_POSITION_USD * 0.9:
            allow_ask = False
            print(f"   ⚠️  Skipping ASK: would increase short position beyond limit")
        # BID (buy) would decrease short → always allow (reducing)

    # If position_size == 0 (flat), allow both sides

    print(f"\n💰 Quote calculation:")
    print(f"   Spread: {spread_bps:.1f} bps")
    print(f"   Skewed mid: ${skewed_mid:.{PRICE_DECIMALS}f}")
    if allow_bid:
        print(f"   Target bid: ${target_bid:.{PRICE_DECIMALS}f} × {bid_size_contracts:.{SIZE_DECIMALS}f}")
    else:
        print(f"   Target bid: SKIPPED (position limit)")
    if allow_ask:
        print(f"   Target ask: ${target_ask:.{PRICE_DECIMALS}f} × {ask_size_contracts:.{SIZE_DECIMALS}f}")
    else:
        print(f"   Target ask: SKIPPED (position limit)")

    # Smart order management
    if SMART_ORDER_MGMT_ENABLED:
        # Check existing orders
        current_orders = get_current_orders()
        bid_order = current_orders['bid']
        ask_order = current_orders['ask']

        need_bid_update = True
        need_ask_update = True

        # Check if bid needs update
        if bid_order:
            existing_bid_price = float(bid_order['limitPx'])
            existing_bid_size = float(bid_order['sz'])

            price_diff_bps = abs(existing_bid_price - target_bid) / target_bid * 10000
            size_diff_pct = abs(existing_bid_size - bid_size_contracts) / bid_size_contracts * 100

            if price_diff_bps < 3 and size_diff_pct < 10:
                print(f"   ✓ Bid unchanged (Δ{price_diff_bps:.1f}bps)")
                need_bid_update = False
            else:
                print(f"   ↻ Updating bid (Δ{price_diff_bps:.1f}bps)")
                cancel_specific_orders(bid_oid=bid_order['oid'])

        # Check if ask needs update
        if ask_order:
            existing_ask_price = float(ask_order['limitPx'])
            existing_ask_size = float(ask_order['sz'])

            price_diff_bps = abs(existing_ask_price - target_ask) / target_ask * 10000
            size_diff_pct = abs(existing_ask_size - ask_size_contracts) / ask_size_contracts * 100

            if price_diff_bps < 3 and size_diff_pct < 10:
                print(f"   ✓ Ask unchanged (Δ{price_diff_bps:.1f}bps)")
                need_ask_update = False
            else:
                print(f"   ↻ Updating ask (Δ{price_diff_bps:.1f}bps)")
                cancel_specific_orders(ask_oid=ask_order['oid'])

        # Place new orders if needed (respecting position limits)
        if need_bid_update and allow_bid:
            success, oid = place_quote(True, target_bid, bid_size_contracts)
            if success:
                print(f"   ✓ Bid placed: ${target_bid:.{PRICE_DECIMALS}f} × {bid_size_contracts:.{SIZE_DECIMALS}f}")
                current_bid_oid = oid
                current_bid_price = target_bid
                current_bid_size = bid_size_contracts
        elif need_bid_update and not allow_bid:
            # Cancel existing bid if position limit prevents new one
            if bid_order:
                cancel_specific_orders(bid_oid=bid_order['oid'])

        if need_ask_update and allow_ask:
            success, oid = place_quote(False, target_ask, ask_size_contracts)
            if success:
                print(f"   ✓ Ask placed: ${target_ask:.{PRICE_DECIMALS}f} × {ask_size_contracts:.{SIZE_DECIMALS}f}")
                current_ask_oid = oid
                current_ask_price = target_ask
                current_ask_size = ask_size_contracts
        elif need_ask_update and not allow_ask:
            # Cancel existing ask if position limit prevents new one
            if ask_order:
                cancel_specific_orders(ask_oid=ask_order['oid'])

    else:
        # Simple mode: cancel all and replace
        cancel_all_orders()
        time.sleep(0.5)

        # Place new orders (respecting position limits)
        if allow_bid:
            place_quote(True, target_bid, bid_size_contracts)
        if allow_ask:
            place_quote(False, target_ask, ask_size_contracts)

    # Update state
    last_mark_price = mark_price
    last_position_usd = position_usd

    print(f"{'='*80}\n")

# ============================================================
# FILL TRACKING
# ============================================================

def record_fills_to_db(fills_list):
    """
    Record fills to database (shared by WebSocket and REST paths)

    Args:
        fills_list: List of fill dicts from Hyperliquid API

    Returns:
        Number of fills recorded
    """
    if not fills_list:
        return 0

    try:
        # Connect to database
        conn = sqlite3.connect('trading_data.db')
        cursor = conn.cursor()

        fills_recorded = 0

        for fill in fills_list:
            try:
                # Parse fill data
                timestamp_ms = int(fill.get('time', 0))
                timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                timestamp = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S.%f+00:00')

                side = fill.get('side', '').lower()  # 'A' = ask/sell, 'B' = bid/buy
                if side == 'a':
                    side = 'sell'
                elif side == 'b':
                    side = 'buy'

                price = float(fill.get('px', 0))
                base_amount = float(fill.get('sz', 0))  # Contracts
                quote_amount = price * base_amount
                fee = float(fill.get('fee', 0))

                # Determine if maker or taker using 'crossed' field
                # crossed=false means maker (didn't cross/take liquidity)
                crossed = fill.get('crossed', True)  # Default to taker if field missing
                is_maker = 0 if crossed else 1

                # Get realized PnL from API (Hyperliquid provides this for position changes)
                # closedPnl is BEFORE fees, so subtract fee to get net PnL
                closed_pnl = float(fill.get('closedPnl', 0.0))
                realized_pnl = closed_pnl - fee  # Net PnL after fees

                # Calculate spread captured
                # For makers, estimate as ~half the configured spread (10 bps config = ~5 bps capture)
                spread_bps = None
                if is_maker:
                    # Rough estimate: half of BASE_SPREAD_BPS
                    spread_bps = BASE_SPREAD_BPS / 2

                order_id = fill.get('oid', f"fill_{timestamp_ms}")

                # Insert to database
                cursor.execute("""
                    INSERT OR IGNORE INTO fills
                    (pair, timestamp, side, price, base_amount, quote_amount,
                     fee, realized_pnl, spread_bps, order_id, is_maker)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    MARKET_DISPLAY, timestamp, side, price, base_amount, quote_amount,
                    fee, realized_pnl, spread_bps, order_id, is_maker
                ))

                fills_recorded += 1

            except Exception as e:
                print(f"   ⚠️  Error recording fill: {e}")
                continue

        conn.commit()
        conn.close()

        if fills_recorded > 0:
            print(f"   ✓ Recorded {fills_recorded} new fills to database")
            # Show summary
            total_volume = sum(float(f.get('sz', 0)) * float(f.get('px', 0)) for f in fills_list)
            total_fees = sum(float(f.get('fee', 0)) for f in fills_list)
            print(f"      Volume: ${total_volume:.2f}, Fees: ${total_fees:.2f}")

        return fills_recorded

    except Exception as e:
        print(f"   ⚠️  Error recording fills to database: {e}")
        import traceback
        traceback.print_exc()
        return 0

def check_and_record_fills():
    """Check for new fills and record them to database"""
    # Get fills from WebSocket if available
    if use_websocket and ws_client and ws_client.is_healthy():
        try:
            new_fills = ws_client.get_new_fills()
            if new_fills:
                print(f"\n📈 Detected {len(new_fills)} new fill(s) from WebSocket")
                return record_fills_to_db(new_fills)
        except Exception as e:
            print(f"   ⚠️  Error getting WebSocket fills: {e}")

    return 0

def get_bot_state_for_metrics():
    """Return bot state for metrics logging"""
    position = get_position()
    account_info = get_account_value()

    # For perps: base_total = position size in contracts, quote_total = account equity
    pos_size = position['size']  # In contracts (e.g., 0.0002 BTC)

    # Check if we have live orders
    bid_live = current_bid_oid is not None
    ask_live = current_ask_oid is not None

    return {
        'mid_price': last_mark_price or 0.0,  # metrics_capture expects 'mid_price'
        'mark_price': last_mark_price or 0.0,
        'position_size': pos_size,
        'position_value': position['position_value'],
        'unrealized_pnl': position['unrealized_pnl'],
        'account_value': account_info['account_value'],
        'margin_ratio': account_info['margin_ratio_pct'],
        'base_spread_bps': BASE_SPREAD_BPS,
        'target_position': TARGET_POSITION_USD,
        'total_value_usd': account_info['account_value'],
        'base_total': pos_size,  # Position in contracts (BTC)
        'quote_total': account_info['account_value'],  # Account equity (USD)
        'bot_running': True,
        'bid_live': bid_live,
        'ask_live': ask_live,
        'our_bid_price': current_bid_price,
        'our_ask_price': current_ask_price,
        'our_bid_size': current_bid_size,
        'our_ask_size': current_ask_size,
        'spread_bps': BASE_SPREAD_BPS,
    }

# ============================================================
# MAIN LOOP
# ============================================================

def set_leverage():
    """Set leverage for this market"""
    try:
        print(f"⚙️  Setting leverage to {LEVERAGE}x for {MARKET_NAME}...")

        # Set leverage using the exchange API
        result = exchange.update_leverage(LEVERAGE, MARKET_NAME, is_cross=True)

        if result.get('status') == 'ok':
            print(f"   ✅ Leverage set to {LEVERAGE}x (cross margin)")
        else:
            print(f"   ⚠️  Leverage update response: {result}")

    except Exception as e:
        print(f"   ⚠️  Error setting leverage: {e}")
        print(f"   ℹ️  Continuing anyway - may need to set leverage manually in UI")

def main():
    """Main market making loop"""
    # Handle SIGTERM (sent by process.terminate()) gracefully
    # This converts SIGTERM to KeyboardInterrupt so cleanup code runs
    def handle_sigterm(signum, frame):
        print("\nReceived SIGTERM signal...")
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, handle_sigterm)

    print(f"Starting {MARKET_DISPLAY} perpetual market maker...\n")
    print("Safety features enabled:")
    print(f"  - Position limit: ±${MAX_POSITION_USD:,.2f}")
    print(f"  - Leverage: {LEVERAGE}x")
    print(f"  - Min margin ratio: {MIN_MARGIN_RATIO_PCT}%")
    print(f"  - Max funding rate: {MAX_FUNDING_RATE_PCT_8H}%")
    print(f"  - Emergency stop loss: {EMERGENCY_STOP_LOSS_PCT}%")
    print(f"  - Post-only orders (Alo) for maker rebates")
    print("\nPress Ctrl+C to stop\n")

    # Set leverage first
    set_leverage()
    print()

    # Register current configuration
    print("📝 Checking bot configuration...")
    current_config = {
        'base_order_size': BASE_ORDER_SIZE,
        'base_spread_bps': BASE_SPREAD_BPS,
        'update_interval_seconds': FALLBACK_CHECK_SECONDS,  # For DB compatibility
        'update_threshold_bps': UPDATE_THRESHOLD_BPS,
        'target_position': TARGET_POSITION_USD,  # DB expects this field name
        'max_position_size': MAX_POSITION_USD,  # DB expects this field name
        'inventory_skew_bps_per_unit': INVENTORY_SKEW_BPS_PER_1K,  # DB expects this field name
        'inventory_skew_threshold': INVENTORY_SKEW_THRESHOLD_USD,  # DB expects this field name
        'max_skew_bps': MAX_SKEW_BPS,
        'min_ask_buffer_bps': None,  # Spot bot field, not used in perp
        'max_spot_perp_deviation_pct': None,  # Spot bot field, not used in perp
        'smart_order_mgmt_enabled': SMART_ORDER_MGMT_ENABLED,
        'leverage': LEVERAGE,  # Perp-specific field
        'max_funding_rate_pct_8h': MAX_FUNDING_RATE_PCT_8H,  # Perp-specific field
    }

    changed_id = param_manager.check_for_changes(current_config)
    if changed_id:
        print(f"   ✅ Configuration updated to parameter set #{changed_id}")
    else:
        print(f"   ✅ Using existing parameter set #{param_manager.get_current_id()}")

    # Start metrics capture
    global metrics_capture
    print("📊 Starting metrics capture...")
    metrics_capture = MetricsCapture(MARKET_DISPLAY, get_bot_state_for_metrics)
    metrics_capture.start()
    print()

    # Start WebSocket connection
    global ws_client, use_websocket
    if use_websocket:
        try:
            print("🌐 Initializing WebSocket connection...")
            ws_client = MarketDataWebSocket(
                spot_coin=MARKET_NAME,  # For perps, just use the market name
                account_address=account_address,
                pair_name=MARKET_NAME,  # Use market name for fill matching
                update_threshold_bps=UPDATE_THRESHOLD_BPS,
                on_update_callback=lambda update_type: None
            )
            ws_client.start()
            print("   ✅ WebSocket ready - real-time data enabled!")
            print()
        except Exception as e:
            print(f"   ⚠️  WebSocket initialization failed: {e}")
            print("   ℹ️  Falling back to REST API mode")
            ws_client = None
            use_websocket = False
            print()

    iteration = 0
    last_quote_update = 0

    try:
        while True:
            iteration += 1

            # Check for rate limit stop
            if rate_limit_hit:
                print("\n🛑 Bot stopped due to rate limiting. Exiting...")
                break

            # Event-driven mode: Wait for WebSocket updates
            if use_websocket and ws_client and ws_client.is_healthy():
                # Block until update or timeout
                ws_client.wait_for_update(timeout=FALLBACK_CHECK_SECONDS)

                # Check what triggered the wake-up
                updates = ws_client.check_updates()

                # Update quotes if something changed or timeout occurred
                time_since_last_update = time.time() - last_quote_update
                should_update = (
                    updates['orderbook'] or
                    updates['fills'] or
                    time_since_last_update > FALLBACK_CHECK_SECONDS
                )

                if should_update:
                    print(f"\n{'#'*80}")
                    print(f"# Iteration {iteration}")
                    if updates['orderbook']:
                        print(f"# Trigger: Orderbook update")
                    elif updates['fills']:
                        print(f"# Trigger: Fill received")
                    else:
                        print(f"# Trigger: {FALLBACK_CHECK_SECONDS}s safety check")
                    print(f"{'#'*80}")

                    try:
                        # Check volatility circuit breaker
                        should_pause, volatility_pct, time_window = check_volatility()

                        if should_pause:
                            # Circuit breaker active - don't update quotes
                            print(f"\n⏸️  Circuit breaker active: {volatility_pct:.2f}% move in {time_window} minutes")
                            print(f"   Waiting for market to stabilize...")
                        else:
                            # Normal trading - update quotes
                            update_quotes()

                        last_quote_update = time.time()

                        if rate_limit_hit:
                            break
                    except Exception as e:
                        print(f"❌ Error in market making loop: {e}")
                        import traceback
                        traceback.print_exc()
                        print("\nContinuing to next iteration...")

                    # Check and record fills
                    try:
                        check_and_record_fills()
                    except Exception as e:
                        print(f"⚠️  Error checking fills: {e}")

            else:
                # WebSocket unhealthy or disabled - try to reconnect if unhealthy
                if use_websocket and ws_client and not ws_client.is_healthy():
                    print(f"\n⚠️  WebSocket connection unhealthy - attempting reconnection...")
                    if ws_client.reconnect():
                        print(f"   ✅ Reconnected! Resuming event-driven mode")
                        continue  # Skip this iteration, resume event-driven mode
                    else:
                        print(f"   ❌ Reconnection failed, falling back to REST mode")

                # REST-only fallback mode
                print(f"\n{'#'*80}")
                print(f"# Iteration {iteration} (REST mode)")
                print(f"{'#'*80}")

                try:
                    # Check volatility circuit breaker
                    should_pause, volatility_pct, time_window = check_volatility()

                    if should_pause:
                        # Circuit breaker active - don't update quotes
                        print(f"\n⏸️  Circuit breaker active: {volatility_pct:.2f}% move in {time_window} minutes")
                        print(f"   Waiting for market to stabilize...")
                    else:
                        # Normal trading - update quotes
                        update_quotes()

                    if rate_limit_hit:
                        break
                except Exception as e:
                    print(f"❌ Error in market making loop: {e}")
                    import traceback
                    traceback.print_exc()
                    print("\nContinuing to next iteration...")

                try:
                    check_and_record_fills()
                except Exception as e:
                    print(f"⚠️  Error checking fills: {e}")

                print(f"\n⏸️  Sleeping {FALLBACK_CHECK_SECONDS}s...")
                time.sleep(FALLBACK_CHECK_SECONDS)

    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down market maker...")

        # Stop WebSocket
        if ws_client:
            ws_client.stop()

        # Stop metrics capture
        if metrics_capture:
            metrics_capture.stop()

        print("Cancelling all orders...")
        cancel_all_orders()
        print("✓ Shutdown complete")

if __name__ == "__main__":
    main()
