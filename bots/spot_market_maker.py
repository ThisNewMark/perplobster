#!/usr/bin/env python3
"""
Generic Spot Market Maker with Oracle-Based Pricing
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

parser = argparse.ArgumentParser(description='Generic spot market maker bot')
parser.add_argument('--config', required=True, help='Path to config file (e.g., config/xmr1-usdc_config.json)')
args = parser.parse_args()

# ============================================================
# CONFIGURATION - LOAD FROM FILE
# ============================================================

print(f"📂 Loading configuration from {args.config}...")
CONFIG = ConfigLoader.load(args.config)
ConfigLoader.validate_trading_config(CONFIG)
print("✅ Configuration loaded and validated")

# Extract pair info from config
PAIR_NAME = CONFIG['pair']  # e.g., "XMR1/USDC" or "KNTQ/USDH"
BASE_TOKEN = PAIR_NAME.split('/')[0]  # e.g., "XMR1" or "KNTQ"
QUOTE_TOKEN = PAIR_NAME.split('/')[1]  # e.g., "USDC" or "USDH"

# Market making settings from config
SPOT_COIN = CONFIG['exchange']['spot_coin']  # e.g., "@404" or "PURR" (for orderbook)
SPOT_COIN_ORDER = CONFIG['exchange'].get('spot_coin_order', SPOT_COIN)  # For order placement (may differ for core assets)
PERP_COIN = CONFIG['exchange'].get('perp_coin')  # e.g., "flx:XMR" or None
PERP_DEX = PERP_COIN.split(':')[0] if PERP_COIN and ':' in PERP_COIN else None

# Decimal precision for prices and sizes
PRICE_DECIMALS = CONFIG['exchange'].get('price_decimals', 2)  # Default to 2 for backward compatibility
SIZE_DECIMALS = CONFIG['exchange'].get('size_decimals', 2)

# Load configuration values from config file
MAX_POSITION_SIZE = CONFIG['position']['max_position_size']
TARGET_POSITION = CONFIG['position']['target_position']

BASE_ORDER_SIZE = CONFIG['trading']['base_order_size']
MIN_ORDER_SIZE = CONFIG['trading']['min_order_size']
SIZE_INCREMENT = CONFIG['trading']['size_increment']

BASE_SPREAD_BPS = CONFIG['trading']['base_spread_bps']
MIN_SPREAD_BPS = CONFIG['trading']['min_spread_bps']
MAX_SPREAD_BPS = CONFIG['trading']['max_spread_bps']

INVENTORY_SKEW_THRESHOLD = CONFIG['inventory'].get('inventory_skew_threshold', 0)  # Dead zone before skewing
INVENTORY_SKEW_BPS_PER_UNIT = CONFIG['inventory']['inventory_skew_bps_per_unit']
MAX_SKEW_BPS = CONFIG['inventory'].get('max_skew_bps', 500)  # Default cap at 500 bps (5%)

MAX_ORACLE_AGE_SECONDS = CONFIG['oracle']['max_oracle_age_seconds']
MAX_ORACLE_JUMP_PCT = CONFIG['oracle']['max_oracle_jump_pct']
MIN_SPREAD_TO_ORACLE_BPS = CONFIG['oracle']['min_spread_to_oracle_bps']

UPDATE_INTERVAL_SECONDS = CONFIG['timing']['update_interval_seconds']
FALLBACK_CHECK_SECONDS = CONFIG['timing'].get('fallback_check_seconds', 30)  # Default to 30s

MAX_QUOTE_COUNT = CONFIG['safety']['max_quote_count']
EMERGENCY_STOP_LOSS_PCT = CONFIG['safety']['emergency_stop_loss_pct']

# ============================================================
# GLOBAL STATE
# ============================================================

last_anchor_price = None
last_anchor_time = None
last_spot_mid = None
cached_anchor = None  # Cache the full anchor dict
last_anchor_fetch = 0  # Timestamp of last fetch
ORACLE_CACHE_SECONDS = 1.0  # Only fetch oracle every N seconds
emergency_stop = False
rate_limit_hit = False  # Flag to stop bot when rate limited
consecutive_connection_failures = 0  # Track connection errors

# Smart order management state
current_bid_oid = None
current_ask_oid = None
current_bid_price = None
current_ask_price = None
current_bid_size = None
current_ask_size = None
last_inventory = None

# Volatility circuit breaker state
price_history = []  # List of (timestamp, price) tuples
circuit_breaker_active = False
circuit_breaker_activated_at = None
last_volatility_check = 0

# Metrics and parameter tracking
param_manager = ParameterManager(PAIR_NAME)
metrics_capture = None
last_fill_check_time = None
last_fill_api_call = 0  # Track last time we called user_fills API

# WebSocket integration
ws_client = None
use_websocket = True  # Can disable for fallback to REST-only mode

# ============================================================
# INITIALIZATION
# ============================================================

# Load config (relative to package root)
print("Loading configuration...")
package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load credentials from .env (falls back to config.json)
sys.path.insert(0, os.path.join(package_root, 'lib'))
from credentials import get_credentials
creds = get_credentials()
main_account_address = creds['account_address']
secret_key = creds['secret_key']

# Check if this pair uses a subaccount
if 'account' in CONFIG and 'subaccount_address' in CONFIG['account']:
    subaccount_address = CONFIG['account']['subaccount_address']
    is_subaccount = True
    vault_address = subaccount_address  # vault_address tells Exchange where to place orders
    account_address = subaccount_address  # account_address for querying positions/balances
    print(f"   Using subaccount: {subaccount_address[:10]}... for {PAIR_NAME}")
else:
    vault_address = None  # None means use main account
    account_address = main_account_address
    is_subaccount = False
    print(f"   Using main account for {PAIR_NAME}")

print(f"\n{'='*80}")
print(f"{PAIR_NAME} SPOT MARKET MAKER")
print(f"{'='*80}")
if is_subaccount:
    print(f"Account: {account_address} (SUBACCOUNT)")
    print(f"Main Account: {main_account_address}")
else:
    print(f"Account: {account_address}")
print(f"Spot Market: {SPOT_COIN} ({PAIR_NAME})")
if PERP_COIN:
    print(f"Anchor Oracle: {PERP_COIN}")
else:
    print(f"Anchor Oracle: None (using spot mid only)")
print(f"Base Spread: {BASE_SPREAD_BPS} bps ({BASE_SPREAD_BPS/100:.2f}%)")
print(f"Order Size: {BASE_ORDER_SIZE} {BASE_TOKEN}")
print(f"Max Position: ±{MAX_POSITION_SIZE} {BASE_TOKEN}")
print(f"Inventory Skew: {INVENTORY_SKEW_BPS_PER_UNIT} bps per {BASE_TOKEN}")
print(f"WebSocket: Event-driven updates (~100ms)")
print(f"Fallback Check: {FALLBACK_CHECK_SECONDS}s")
print(f"{'='*80}\n")

# Setup Hyperliquid API
base_url = constants.MAINNET_API_URL
info = Info(base_url=base_url, skip_ws=True, perp_dexs=["", "xyz", "flx"])

# Create account from main wallet's private key (used for signing)
account = Account.from_key(secret_key)

# Create exchange - vault_address tells Exchange where to place orders
# For subaccounts: wallet signs with main account, vault_address = subaccount
# For main account: vault_address = None
exchange = Exchange(
    wallet=account,
    base_url=base_url,
    account_address=main_account_address or None,
    vault_address=vault_address,
    perp_dexs=["", "xyz", "flx"]
)

# Auto-approve builder fee on first run (one-time, supports Perp Lobster development)
ensure_builder_fee_approved(exchange)

print("✓ Connected to Hyperliquid")
print("✓ Spot and perp metadata loaded\n")

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def reinitialize_connections():
    """Recreate API connections (fixes stale connections after sleep/VPN issues)"""
    global info, exchange

    try:
        print(f"   🔄 Reinitializing API connections...")

        # Small delay before reconnecting
        time.sleep(2)

        # Recreate Info object (fresh connection pool)
        new_info = Info(base_url=constants.MAINNET_API_URL, skip_ws=True, perp_dexs=["", "xyz", "flx"])

        # Recreate Exchange object (fresh connection pool)
        account = Account.from_key(secret_key)
        new_exchange = Exchange(
            wallet=account,
            base_url=constants.MAINNET_API_URL,
            account_address=main_account_address or None,
            vault_address=vault_address,
            perp_dexs=["", "xyz", "flx"]
        )

        # Test the connection by making a simple API call
        test = new_info.post("/info", {"type": "l2Book", "coin": "@260"})
        if not test:
            raise Exception("Test API call failed")

        # If we got here, connections are good - update globals
        info = new_info
        exchange = new_exchange

        print(f"   ✓ Connections reinitialized and tested")
        return True
    except Exception as e:
        print(f"   ❌ Failed to reinitialize: {e}")
        return False

def get_anchor_price():
    """Get anchor price from perp oracle with validation"""
    global last_anchor_price, last_anchor_time, cached_anchor, last_anchor_fetch

    # If no perp oracle configured, return spot-based anchor
    if PERP_COIN is None:
        print("   ✓ Using spot mid as anchor (no oracle configured)")
        # Get spot orderbook
        spot_ob = get_spot_orderbook()
        if not spot_ob:
            return None

        spot_mid = spot_ob['mid']
        anchor = {
            "price": spot_mid,
            "bid": spot_ob['best_bid'],
            "ask": spot_ob['best_ask'],
            "spread_bps": spot_ob['spread_bps'],
            "source": "Spot mid"
        }

        # Cache it
        cached_anchor = anchor
        last_anchor_fetch = time.time()
        last_anchor_price = spot_mid

        return anchor

    # Return cached value if fresh (< 1 second old)
    current_time = time.time()
    if cached_anchor and (current_time - last_anchor_fetch) < ORACLE_CACHE_SECONDS:
        return cached_anchor

    # Check if we should use perp oracle price instead of perp book
    use_oracle_price = CONFIG['exchange'].get('use_perp_oracle_price', False)

    try:
        # Fetch perp oracle price if enabled
        if use_oracle_price:
            # Get oracle price from meta_and_asset_ctxs
            # Response format: [{"universe": [...], "assetCtxs": [...]}]
            meta_response = info.meta_and_asset_ctxs()

            # Extract universe (list of asset contexts)
            universe = []
            if isinstance(meta_response, list) and len(meta_response) > 0:
                universe = meta_response[0].get('universe', [])

            # Find the asset context for our perp
            oracle_price = None
            for asset_ctx in universe:
                if asset_ctx.get('name') == PERP_COIN:
                    oracle_px = asset_ctx.get('oraclePx')
                    if oracle_px:
                        oracle_price = float(oracle_px)
                        break
                    # Fallback to markPx if oraclePx not available
                    mark_px = asset_ctx.get('markPx')
                    if mark_px:
                        oracle_price = float(mark_px)
                        break

            if not oracle_price:
                print(f"   ℹ️  Oracle price not available for {PERP_COIN}, using perp book")
                use_oracle_price = False
            else:
                # Still fetch perp book for spread info
                perp_payload = {"type": "l2Book", "coin": PERP_COIN}
                if PERP_DEX:
                    perp_payload["dex"] = PERP_DEX
                perp_book = info.post("/info", perp_payload)
                perp_bids = perp_book.get("levels", [[], []])[0]
                perp_asks = perp_book.get("levels", [[], []])[1]

                if perp_bids and perp_asks:
                    perp_bid = float(perp_bids[0]["px"])
                    perp_ask = float(perp_asks[0]["px"])
                    perp_mid = (perp_bid + perp_ask) / 2
                    perp_spread_bps = ((perp_ask - perp_bid) / perp_mid) * 10000

                    # Use oracle price as anchor, but keep book spread info
                    anchor = {
                        "price": oracle_price,
                        "bid": perp_bid,
                        "ask": perp_ask,
                        "spread_bps": perp_spread_bps,
                        "source": "Oracle"
                    }

                    cached_anchor = anchor
                    last_anchor_fetch = time.time()
                    last_anchor_price = oracle_price

                    return anchor

        # Standard perp book fetch (if not using oracle or fallback)
        perp_payload = {"type": "l2Book", "coin": PERP_COIN}
        if PERP_DEX:
            perp_payload["dex"] = PERP_DEX
        perp_book = info.post("/info", perp_payload)
        perp_bids = perp_book.get("levels", [[], []])[0]
        perp_asks = perp_book.get("levels", [[], []])[1]

        if not perp_bids or not perp_asks:
            print(f"   ⚠️  No liquidity on {PERP_COIN} perp")
            return None

        perp_bid = float(perp_bids[0]["px"])
        perp_ask = float(perp_asks[0]["px"])
        perp_mid = (perp_bid + perp_ask) / 2
        current_time = time.time()

        # Validate oracle quality
        is_valid = True
        reasons = []

        # Check 1: Oracle jump validation (circuit breaker)
        if last_anchor_price is not None:
            price_change_pct = abs((perp_mid - last_anchor_price) / last_anchor_price) * 100
            if price_change_pct > MAX_ORACLE_JUMP_PCT:
                is_valid = False
                reasons.append(f"Oracle jumped {price_change_pct:.2f}% (max {MAX_ORACLE_JUMP_PCT}%)")

        # Check 2: Staleness (for now just log, we don't have timestamp from API)
        # In production, you'd want to check meta_and_asset_ctxs for funding timestamp

        # Check 3: Reasonable spread on perp
        perp_spread_bps = ((perp_ask - perp_bid) / perp_mid) * 10000
        if perp_spread_bps > 100:  # >1% spread is suspicious
            is_valid = False
            reasons.append(f"Perp spread too wide ({perp_spread_bps:.0f} bps)")

        if not is_valid:
            print(f"   ❌ Oracle validation failed:")
            for reason in reasons:
                print(f"      - {reason}")
            return None

        # Update globals
        last_anchor_price = perp_mid
        last_anchor_time = current_time

        # Cache the result
        anchor_result = {
            "price": perp_mid,
            "bid": perp_bid,
            "ask": perp_ask,
            "spread_bps": perp_spread_bps,
            "time": current_time,
            "source": "Perp mid"
        }
        cached_anchor = anchor_result
        last_anchor_fetch = current_time

        return anchor_result

    except Exception as e:
        print(f"   ❌ Error fetching anchor price: {e}")
        return None

def get_position_info():
    """Get current spot balances for the spot market"""
    try:
        # For spot markets, balances are in user_state.balances, NOT assetPositions
        # assetPositions is for perps only
        print(f"   [BALANCE DEBUG] Querying user_state for: {account_address[:10]}...")
        user_state = info.user_state(account_address)

        # balances format: [{coin: "404", hold: "0.0", total: "0.39"}]
        # coin "404" = XMR1 token ID
        # coin "0" = USDC token ID
        balances = user_state.get("balances", [])
        print(f"   [BALANCE DEBUG] Raw balances: {balances}")

        base_balance = 0.0
        usdc_balance = 0.0

        for balance_entry in balances:
            coin_id = balance_entry.get("coin")
            total = balance_entry.get("total", "0")
            hold = balance_entry.get("hold", "0")  # Amount locked in orders

            # Available = total - hold
            available = float(total) - float(hold)

            print(f"   [BALANCE DEBUG] Coin {coin_id}: total={total}, hold={hold}, available={available}")

            # Map coin IDs to tokens
            # Note: Coin IDs vary by token:
            # - "0" = USDC (always)
            # - "404" = XMR1 (builder asset @260)
            # - "PURR" = PURR (core asset, uses string name not numeric ID)
            # For builder assets (@XXX format), coin_id is the numeric index
            # For core assets, coin_id is the token name string

            if coin_id == "0":  # USDC token ID (legacy)
                usdc_balance = available
            elif coin_id == QUOTE_TOKEN:  # Match quote currency by name (USDC, USDH, etc.)
                usdc_balance = available
            elif coin_id == SPOT_COIN.replace('@', ''):  # Match builder asset by ID
                base_balance = available
            elif coin_id == BASE_TOKEN:  # Match core asset by name
                base_balance = available

        # For spot: "position" = base token balance
        # We don't track entry price for spot (no leverage, just holdings)
        print(f"   [BALANCE DEBUG] Final balances: {BASE_TOKEN}={base_balance}, {QUOTE_TOKEN}={usdc_balance}")
        return base_balance, None

    except Exception as e:
        print(f"   ⚠️  Error getting balances: {e}")
        import traceback
        traceback.print_exc()
        return 0.0, None

def get_spot_orderbook():
    """Get spot market orderbook (WebSocket preferred, REST fallback)"""
    global ws_client, use_websocket

    # Try WebSocket first if enabled and healthy
    if use_websocket and ws_client and ws_client.is_healthy():
        try:
            orderbook = ws_client.get_orderbook()
            if orderbook:
                return orderbook
        except Exception as e:
            print(f"   ⚠️  WebSocket orderbook failed, falling back to REST: {e}")

    # Fallback to REST API
    try:
        # Spot markets don't use dex parameter
        payload = {"type": "l2Book", "coin": SPOT_COIN}
        book = info.post("/info", payload)
        bids = book.get("levels", [[], []])[0]
        asks = book.get("levels", [[], []])[1]

        if not bids or not asks:
            return None

        best_bid = float(bids[0]["px"])
        best_ask = float(asks[0]["px"])
        mid = (best_bid + best_ask) / 2

        # Calculate depth
        bid_depth = sum(float(b["sz"]) for b in bids[:5])
        ask_depth = sum(float(a["sz"]) for a in asks[:5])

        return {
            "mid": mid,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
            "spread_bps": ((best_ask - best_bid) / mid) * 10000,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "bids": bids,
            "asks": asks
        }

    except Exception as e:
        print(f"   ❌ Error fetching spot orderbook: {e}")
        return None

def cancel_all_orders():
    """Cancel all open orders for this spot market"""
    try:
        # Spot orders don't use dex parameter
        open_orders = info.open_orders(account_address)
        # Check both formats since core assets may use pair format, builder assets use @index
        spot_orders = [o for o in open_orders if o.get("coin") in [SPOT_COIN, SPOT_COIN_ORDER]]

        if spot_orders:
            print(f"   Cancelling {len(spot_orders)} existing orders...")
            for order in spot_orders:
                try:
                    # Use the coin format from the order itself for cancellation
                    cancel_result = exchange.cancel(order["coin"], order["oid"])
                except Exception as e:
                    print(f"   ⚠️  Error canceling order {order['oid']}: {e}")

            # IMPORTANT: Wait longer for cancellations to fully process
            # Exchange needs time to release "hold" funds before new orders
            time.sleep(1.5)  # Empirically measured: max 1.142s + 0.36s safety margin
            return len(spot_orders)
        return 0
    except Exception as e:
        print(f"   ⚠️  Error cancelling orders: {e}")
        return 0

def place_quote(is_buy, price, size):
    """Place a spot limit order (maker-only)

    Returns: (success: bool, order_id: str or None)
    """
    global rate_limit_hit

    try:
        # Round price to configured decimal places (varies by asset)
        price = round(price, PRICE_DECIMALS)

        # Round size to valid increment
        size = round(size / SIZE_INCREMENT) * SIZE_INCREMENT

        # Enforce minimum size
        if size < MIN_ORDER_SIZE:
            return False, None

        # Use post-only orders to ensure maker rebates (ALO = Add Liquidity Only)
        order_type = {"limit": {"tif": "Alo"}}

        # Spot orders use standard order() call without dex specification
        # Use SPOT_COIN_ORDER which is pair format for core assets (e.g., "PURR/USDC")
        # or @index format for builder assets (e.g., "@404")
        result = exchange.order(
            SPOT_COIN_ORDER,  # coin (pair format for core, @index for builder)
            is_buy,           # is_buy
            size,             # sz
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

# ============================================================
# SMART ORDER MANAGEMENT
# ============================================================

def get_current_orders():
    """Get current open orders for this spot market and return as dict by side

    Returns: {'bid': order_dict or None, 'ask': order_dict or None}
    """
    try:
        open_orders = info.open_orders(account_address)
        # Check both formats since core assets may use pair format, builder assets use @index
        spot_orders = [o for o in open_orders if o.get("coin") in [SPOT_COIN, SPOT_COIN_ORDER]]

        bid_order = None
        ask_order = None

        for order in spot_orders:
            if order.get("side") == "B":  # Buy
                bid_order = order
            elif order.get("side") == "A":  # Ask/Sell
                ask_order = order

        return {'bid': bid_order, 'ask': ask_order}
    except Exception as e:
        print(f"   ⚠️  Error fetching current orders: {e}")
        return {'bid': None, 'ask': None}

def should_update_quotes(current_spot_mid, position):
    """Determine if we need to update quotes based on market changes

    Returns: (should_update: bool, reason: str)
    """
    global last_spot_mid, last_inventory

    # First run - always update
    if last_spot_mid is None:
        return True, "first_run"

    # Check if spot mid moved significantly (PRIMARY pricing trigger)
    mid_change_bps = abs(current_spot_mid - last_spot_mid) / last_spot_mid * 10000
    if mid_change_bps > 3:  # 3 bps threshold (tightened from 5 to cancel faster on market moves)
        return True, f"spot_mid_moved_{mid_change_bps:.1f}bps"

    # Check if inventory changed (we got filled)
    if last_inventory is not None:
        inventory_delta = abs(position - last_inventory)
        if inventory_delta > 0.05:  # More than 0.05 XMR change
            return True, f"inventory_changed_{inventory_delta:.2f}"

    return False, "no_significant_change"

def cancel_specific_orders(bid_oid=None, ask_oid=None):
    """Cancel specific orders by OID

    Args:
        bid_oid: Order ID of bid to cancel (or None to skip)
        ask_oid: Order ID of ask to cancel (or None to skip)

    Returns: (bid_cancelled: bool, ask_cancelled: bool)
    """
    bid_cancelled = False
    ask_cancelled = False

    try:
        if bid_oid:
            try:
                # Use SPOT_COIN_ORDER since that's the format we used to place orders
                exchange.cancel(SPOT_COIN_ORDER, bid_oid)
                bid_cancelled = True
                print(f"   Cancelled bid {bid_oid}")
            except Exception as e:
                print(f"   ⚠️  Error canceling bid: {e}")

        if ask_oid:
            try:
                # Use SPOT_COIN_ORDER since that's the format we used to place orders
                exchange.cancel(SPOT_COIN_ORDER, ask_oid)
                ask_cancelled = True
                print(f"   Cancelled ask {ask_oid}")
            except Exception as e:
                print(f"   ⚠️  Error canceling ask: {e}")

        # Small delay if we cancelled anything
        if bid_cancelled or ask_cancelled:
            time.sleep(1.5)

    except Exception as e:
        print(f"   ⚠️  Error in cancel_specific_orders: {e}")

    return bid_cancelled, ask_cancelled

def get_bot_state_for_metrics():
    """Return current bot state for metrics capture"""
    global current_bid_oid, current_ask_oid
    global current_bid_price, current_ask_price
    global current_bid_size, current_ask_size
    global last_spot_mid

    try:
        # Get current balances
        spot_state = info.post("/info", {
            "type": "spotClearinghouseState",
            "user": account_address
        })
        balances = spot_state.get("balances", [])

        xmr_balance = 0.0
        xmr_total = 0.0
        usdc_balance = 0.0
        usdc_total = 0.0

        for balance_entry in balances:
            coin_name = balance_entry.get("coin")
            total = float(balance_entry.get("total", "0"))
            hold = float(balance_entry.get("hold", "0"))
            available = total - hold

            if coin_name == BASE_TOKEN:
                xmr_balance = available
                xmr_total = total
            elif coin_name == QUOTE_TOKEN:
                usdc_balance = available
                usdc_total = total

        # Get current market price
        spot_ob = get_spot_orderbook()
        mid_price = spot_ob['mid'] if spot_ob else last_spot_mid
        bid_price = spot_ob['best_bid'] if spot_ob else None
        ask_price = spot_ob['best_ask'] if spot_ob else None
        spread_bps = spot_ob['spread_bps'] if spot_ob else None

        # Calculate total value
        total_value_usd = xmr_total * mid_price + usdc_total if mid_price else 0

        return {
            'parameter_set_id': param_manager.get_current_id(),
            'base_balance': xmr_balance,
            'quote_balance': usdc_balance,
            'base_total': xmr_total,
            'quote_total': usdc_total,
            'mid_price': mid_price,
            'bid_price': bid_price,
            'ask_price': ask_price,
            'spread_bps': spread_bps,
            'total_value_usd': total_value_usd,
            'bot_running': True,
            'bid_live': current_bid_oid is not None,
            'ask_live': current_ask_oid is not None,
            'our_bid_price': current_bid_price,
            'our_ask_price': current_ask_price,
            'our_bid_size': current_bid_size,
            'our_ask_size': current_ask_size,
        }
    except Exception as e:
        print(f"   ⚠️  Error getting bot state for metrics: {e}")
        return {}

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
                # Format with space separator to match metrics_1min table
                timestamp = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S.%f+00:00')

                side = fill.get('side', '').lower()  # 'A' = ask/sell, 'B' = bid/buy
                if side == 'a':
                    side = 'sell'
                elif side == 'b':
                    side = 'buy'

                price = float(fill.get('px', 0))
                base_amount = float(fill.get('sz', 0))
                quote_amount = price * base_amount
                fee = float(fill.get('fee', 0))

                # Determine if maker or taker (negative fee = maker rebate)
                is_maker = 1 if fee < 0 else 0

                # For now, set realized_pnl to 0 (can calculate later with inventory tracking)
                realized_pnl = 0

                # Calculate spread captured (rough estimate from fee)
                spread_bps = None
                if is_maker and fee != 0:
                    # Maker gets ~0.2 bps rebate
                    spread_bps = abs(fee / quote_amount * 10000) * 2  # Rough estimate

                order_id = fill.get('oid', f"fill_{timestamp_ms}")

                # Insert to database
                cursor.execute("""
                    INSERT OR IGNORE INTO fills
                    (pair, timestamp, side, price, base_amount, quote_amount,
                     fee, realized_pnl, spread_bps, order_id, is_maker)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    PAIR_NAME, timestamp, side, price, base_amount, quote_amount,
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
    """Fetch recent fills from Hyperliquid and record to database"""
    global last_fill_check_time, last_fill_api_call, ws_client, use_websocket

    # Try WebSocket fills first (instant, no rate limiting)
    ws_fills = []
    if use_websocket and ws_client and ws_client.is_healthy():
        try:
            ws_fills = ws_client.get_new_fills()
            if ws_fills:
                # Process WebSocket fills immediately
                return record_fills_to_db(ws_fills)
        except Exception as e:
            print(f"   ⚠️  WebSocket fills failed: {e}")

    # Fallback: Only check REST API fills once per minute to avoid rate limiting
    current_time = time.time()
    if current_time - last_fill_api_call < 60:
        return 0  # Skip this check

    last_fill_api_call = current_time

    try:
        # Get fills from Hyperliquid
        all_fills = info.user_fills(account_address)

        # Filter for this spot market's fills only
        # Check both formats since core assets return fills in pair format (e.g., "PURR/USDC")
        spot_fills = [f for f in all_fills if f.get('coin') in [SPOT_COIN, SPOT_COIN_ORDER, PAIR_NAME]]

        # Debug: Show total fills found
        if spot_fills and last_fill_check_time is None:
            print(f"   [FILLS DEBUG] Found {len(spot_fills)} total {BASE_TOKEN} fills in history")

        # Only check fills from last 5 minutes to avoid duplicates
        if last_fill_check_time is None:
            # First run - get last 5 minutes
            cutoff_time = int((datetime.now(timezone.utc).timestamp() - 300) * 1000)
            print(f"   [FILLS DEBUG] First run - checking fills since {datetime.fromtimestamp(cutoff_time/1000, tz=timezone.utc)}")
        else:
            cutoff_time = last_fill_check_time

        recent_fills = [f for f in spot_fills if int(f.get('time', 0)) > cutoff_time]

        # Update last check time to most recent fill
        if recent_fills:
            last_fill_check_time = max(int(f.get('time', 0)) for f in recent_fills)

        # Record fills to database using shared function
        return record_fills_to_db(recent_fills)

    except Exception as e:
        print(f"   ⚠️  Error checking fills: {e}")
        import traceback
        traceback.print_exc()
        return 0

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

# ============================================================
# MARKET MAKING LOGIC
# ============================================================

def update_quotes():
    """Smart quote management - updates only when needed, based on spot market"""
    global emergency_stop, consecutive_connection_failures
    global last_spot_mid, last_inventory
    global current_bid_oid, current_ask_oid, current_bid_price, current_ask_price
    global current_bid_size, current_ask_size

    # Emergency stop check
    if emergency_stop:
        print("\n🚨 EMERGENCY STOP ACTIVE - Not quoting")
        print("   Restart bot to resume")
        return

    print(f"\n{'='*80}")
    print(f"Market Update - {time.strftime('%H:%M:%S')}")
    print(f"{'='*80}")

    # Step 1: Get anchor price from perp
    if PERP_COIN:
        use_oracle = CONFIG['exchange'].get('use_perp_oracle_price', False)
        if use_oracle:
            print(f"1. Fetching oracle price for {PERP_COIN} perp...")
        else:
            print(f"1. Fetching anchor price from {PERP_COIN} perp...")
    else:
        print("1. No perp oracle configured (using spot mid only)...")
    anchor = get_anchor_price()

    if not anchor:
        consecutive_connection_failures += 1
        print(f"   ❌ Cannot get valid anchor price - SKIPPING THIS CYCLE")
        print(f"   (Safety: Do not quote without reliable oracle)")
        print(f"   Consecutive failures: {consecutive_connection_failures}")

        # After 3 consecutive failures, try to reconnect
        if consecutive_connection_failures >= 3:
            print(f"\n   ⚠️  {consecutive_connection_failures} consecutive failures detected")
            print(f"   Possible cause: Computer sleep, VPN disconnect, or network issue")
            print(f"   Attempting to reconnect...")

            if reinitialize_connections():
                consecutive_connection_failures = 0  # Reset counter
                print(f"   ✓ Reconnection successful - will retry next cycle")
            else:
                print(f"   ❌ Reconnection failed - will retry in 30s")

        return

    # Reset failure counter on success
    consecutive_connection_failures = 0

    anchor_price = anchor["price"]
    source = anchor.get("source", "Unknown")
    print(f"   ✓ Anchor: ${anchor_price:.{PRICE_DECIMALS}f} ({source})")
    print(f"      Perp bid/ask: ${anchor['bid']:.{PRICE_DECIMALS}f} / ${anchor['ask']:.{PRICE_DECIMALS}f}")
    print(f"      Perp spread: {anchor['spread_bps']:.1f} bps")

    # Small delay to avoid rate limiting
    time.sleep(0.5)

    # Step 2: Get current spot balances
    print("\n2. Checking balances...")

    # Get balances from spotClearinghouseState (correct endpoint for spot balances)
    # Retry with backoff on rate limit errors
    max_retries = 3
    for attempt in range(max_retries):
        try:
            spot_state = info.post("/info", {
                "type": "spotClearinghouseState",
                "user": account_address
            })
            balances = spot_state.get("balances", [])

            xmr_balance = 0.0
            usdc_balance = 0.0

            xmr_total = 0.0
            for balance_entry in balances:
                coin_name = balance_entry.get("coin")  # "USDC", "XMR1", etc.
                total = balance_entry.get("total", "0")
                hold = balance_entry.get("hold", "0")
                available = float(total) - float(hold)

                if coin_name == BASE_TOKEN:
                    xmr_balance = available
                    xmr_total = float(total)  # Total including holds
                elif coin_name == QUOTE_TOKEN:
                    usdc_balance = available

            position = xmr_balance  # For order placement checks (available only)
            position_total = xmr_total  # For inventory change detection (total including holds)
            break  # Success, exit retry loop

        except Exception as e:
            error_str = str(e)
            if '429' in error_str:  # Rate limit error
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                    print(f"   ⚠️  Rate limited (429) - waiting {wait_time}s before retry {attempt + 2}/{max_retries}")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"   ⚠️  Rate limited after {max_retries} attempts - skipping this cycle")
                    return
            else:
                print(f"   ⚠️  Error getting balances: {e}")
                import traceback
                traceback.print_exc()
                return

    entry_price = None  # No entry price tracking for spot

    print(f"   {BASE_TOKEN} balance: {xmr_balance:.4f} (Target: {TARGET_POSITION:.2f})")
    print(f"   {QUOTE_TOKEN} balance: ${usdc_balance:.2f}")

    # Step 3: Get spot orderbook
    print("\n3. Fetching spot orderbook...")
    spot_ob = get_spot_orderbook()

    if not spot_ob:
        print("   ❌ Cannot get spot orderbook - SKIPPING THIS CYCLE")
        return

    print(f"   Spot mid: ${spot_ob['mid']:.{PRICE_DECIMALS}f}")
    print(f"   Spot bid/ask: ${spot_ob['best_bid']:.{PRICE_DECIMALS}f} / ${spot_ob['best_ask']:.{PRICE_DECIMALS}f}")
    print(f"   Spot spread: {spot_ob['spread_bps']:.1f} bps")
    print(f"   Depth (top 5): {spot_ob['bid_depth']:.2f} / {spot_ob['ask_depth']:.2f} {BASE_TOKEN}")

    # Step 3.5: Smart check - do we need to update?
    print("\n3.5. Checking if update needed...")

    spot_mid = spot_ob['mid']

    # Update price history for volatility monitoring
    update_price_history(spot_mid)

    needs_update, reason = should_update_quotes(spot_mid, position_total)

    global last_inventory, last_spot_mid, current_bid_oid, current_ask_oid
    global current_bid_price, current_ask_price

    if not needs_update:
        print(f"   ✓ No update needed ({reason})")

        # Verify orders are still live
        current_orders = get_current_orders()

        bid_live = current_orders['bid'] is not None
        ask_live = current_orders['ask'] is not None

        if bid_live and ask_live:
            print(f"   ✓ Both sides live - quotes stable")
            last_spot_mid = spot_mid
            last_inventory = position_total
            return
        elif bid_live or ask_live:
            # One side is missing - check if this is expected due to balance constraints
            # Don't force update if missing side is due to insufficient inventory
            bid_possible = position_total < MAX_POSITION_SIZE and usdc_balance >= (BASE_ORDER_SIZE * spot_mid * 0.5)
            ask_possible = position >= BASE_ORDER_SIZE

            # Only force update if a side is missing that SHOULD be there
            if (not bid_live and bid_possible) or (not ask_live and ask_possible):
                print(f"   ⚠️  Expected order missing - will update")
                needs_update = True
                reason = "one_side_missing"
            else:
                # One-sided market is expected (insufficient balance for other side)
                print(f"   ✓ One-sided market expected (insufficient balance) - quotes stable")
                last_spot_mid = spot_mid
                last_inventory = position_total
                return
        else:
            print(f"   ⚠️  No orders live - forcing update")
            needs_update = True
            reason = "no_orders_live"

    print(f"   🔄 Update needed: {reason}")

    # Step 4: Calculate quoting mid with inventory skew
    print("\n4. Calculating quoting mid with inventory skew...")

    # PRIMARY: Use SPOT mid (where actual trading is happening)
    base_mid = spot_ob['mid']

    # SECONDARY: Check deviation from perp oracle
    spot_vs_perp_diff_pct = ((base_mid - anchor_price) / anchor_price) * 100
    spot_vs_perp_diff_bps = spot_vs_perp_diff_pct * 100

    print(f"   Spot mid: ${base_mid:.{PRICE_DECIMALS}f}")
    if PERP_COIN and anchor_price:
        print(f"   Perp anchor: ${anchor_price:.{PRICE_DECIMALS}f}")
        print(f"   Deviation: {spot_vs_perp_diff_bps:+.0f} bps ({spot_vs_perp_diff_pct:+.2f}%)")

    # Circuit breaker: If spot deviates too much from perp, pause
    # Skip if deviation >100% (indicates wrong oracle/spot coin mismatch)
    MAX_SPOT_PERP_DEVIATION_PCT = 5.0  # 5% max deviation
    if anchor_price and abs(spot_vs_perp_diff_pct) > MAX_SPOT_PERP_DEVIATION_PCT and abs(spot_vs_perp_diff_pct) < 100:
        print(f"   🚨 CIRCUIT BREAKER: Spot deviates {spot_vs_perp_diff_pct:+.2f}% from perp!")
        print(f"      Max allowed: ±{MAX_SPOT_PERP_DEVIATION_PCT}%")
        print(f"      PAUSING - Market may be dislocated")
        return
    elif anchor_price and abs(spot_vs_perp_diff_pct) > 100:
        print(f"   ⚠️  Perp oracle mismatch detected ({spot_vs_perp_diff_pct:+.0f}% deviation)")
        print(f"   Using spot mid only (perp oracle may be wrong market)")

    # Emergency sell check: If spot drops significantly below oracle (crash protection)
    emergency_sell_threshold = CONFIG['safety'].get('emergency_sell_if_below_oracle_pct')
    if emergency_sell_threshold and PERP_COIN and anchor_price:
        # Only trigger if spot is BELOW oracle (negative deviation)
        if spot_vs_perp_diff_pct < -emergency_sell_threshold:
            print(f"\n{'='*80}")
            print(f"🚨 EMERGENCY SELL TRIGGERED!")
            print(f"{'='*80}")
            print(f"Spot is {spot_vs_perp_diff_pct:.2f}% below oracle (threshold: -{emergency_sell_threshold}%)")
            print(f"   Spot: ${base_mid:.{PRICE_DECIMALS}f}")
            print(f"   Oracle: ${anchor_price:.{PRICE_DECIMALS}f}")
            print(f"\nExecuting emergency market sell of entire position...")

            # Cancel all existing orders first
            try:
                cancel_all_orders()
            except:
                pass

            # Place market sell order for entire position
            if position > MIN_ORDER_SIZE:
                try:
                    print(f"   Selling {position:.{SIZE_DECIMALS}f} {BASE_TOKEN} at market...")
                    result = exchange.market_order(
                        SPOT_COIN_ORDER,
                        False,  # is_buy = False (sell)
                        position,  # Size = entire position
                        None  # No limit price (market order)
                    )
                    print(f"   ✓ Emergency sell order placed!")
                    print(f"   Result: {result}")
                except Exception as e:
                    print(f"   ❌ Emergency sell failed: {e}")

            # Stop the bot
            emergency_stop = True
            print(f"\n🛑 Bot stopped after emergency sell")
            print(f"{'='*80}\n")
            return

    # Apply inventory skew based on TARGET_POSITION
    # If we have MORE than target: skew DOWN (encourage selling)
    # If we have LESS than target: skew UP (encourage buying)
    inventory_delta = position - TARGET_POSITION

    # Apply threshold/dead zone - only skew if beyond threshold
    if abs(inventory_delta) <= INVENTORY_SKEW_THRESHOLD:
        # Within threshold - no skew
        inventory_skew_bps = 0
    else:
        # Beyond threshold - apply skew only to the excess
        if inventory_delta > 0:
            excess = inventory_delta - INVENTORY_SKEW_THRESHOLD
        else:
            excess = inventory_delta + INVENTORY_SKEW_THRESHOLD
        inventory_skew_bps = -excess * INVENTORY_SKEW_BPS_PER_UNIT

        # Cap the skew at MAX_SKEW_BPS to prevent extreme pricing
        if abs(inventory_skew_bps) > MAX_SKEW_BPS:
            # Preserve the sign: if negative, cap to -MAX_SKEW_BPS; if positive, cap to +MAX_SKEW_BPS
            capped_skew = -MAX_SKEW_BPS if inventory_skew_bps < 0 else MAX_SKEW_BPS
            print(f"   ⚠️  Skew capped: {inventory_skew_bps:+.0f} bps → {capped_skew:+.0f} bps (max: ±{MAX_SKEW_BPS} bps)")
            inventory_skew_bps = capped_skew

    skewed_mid = base_mid * (1 + inventory_skew_bps / 10000)

    print(f"   Target inventory: {TARGET_POSITION:.2f} {BASE_TOKEN}")
    print(f"   Current inventory: {position:.2f} {BASE_TOKEN}")
    if abs(inventory_delta) > INVENTORY_SKEW_THRESHOLD:
        print(f"   Inventory delta: {inventory_delta:+.2f} (excess: {excess:+.2f}) → skew {inventory_skew_bps:+.0f} bps")
        print(f"   Skewed mid: ${skewed_mid:.5f}")
    else:
        print(f"   Inventory delta: {inventory_delta:+.2f} (within ±{INVENTORY_SKEW_THRESHOLD} threshold - no skew)")

    quoting_mid = skewed_mid

    # Step 5: Calculate spreads with dynamic adjustments
    print("\n5. Calculating spreads...")

    # Start with base spread
    spread_bps = BASE_SPREAD_BPS

    # Widen spread if perp is volatile (wide spread on anchor)
    # Only do this if we have a perp oracle (not using spot as anchor)
    if PERP_COIN and anchor['spread_bps'] > 20:
        spread_adjustment = anchor['spread_bps'] / 4
        spread_bps += spread_adjustment
        print(f"   Widening for perp volatility: +{spread_adjustment:.0f} bps")

    # Widen spread if spot deviates from perp (risk signal)
    # Only do this if we have a perp oracle
    if PERP_COIN and abs(spot_vs_perp_diff_pct) > 1.0:
        deviation_spread_add = abs(spot_vs_perp_diff_bps) / 2  # Half the deviation
        spread_bps += deviation_spread_add
        print(f"   Widening for spot-perp deviation: +{deviation_spread_add:.0f} bps")

    # Widen spread if spot is thin
    if spot_ob['bid_depth'] < 2.0 or spot_ob['ask_depth'] < 2.0:
        spread_bps += 20
        print(f"   Widening for thin spot book: +20 bps")

    # Widen spread as position grows (inventory risk)
    position_pct = abs(position) / MAX_POSITION_SIZE
    if position_pct > 0.5:
        inventory_spread_add = 30 * (position_pct - 0.5) * 2  # Up to +30 bps
        spread_bps += inventory_spread_add
        print(f"   Widening for inventory risk: +{inventory_spread_add:.0f} bps")

    # Enforce limits
    spread_bps = max(MIN_SPREAD_BPS, min(MAX_SPREAD_BPS, spread_bps))

    print(f"   Final spread: {spread_bps:.0f} bps")

    # Step 6: Calculate quote prices
    half_spread_bps = spread_bps / 2
    bid_price = quoting_mid * (1 - half_spread_bps / 10000)
    ask_price = quoting_mid * (1 + half_spread_bps / 10000)

    # Display prices with appropriate precision
    print(f"   Bid: ${bid_price:.{PRICE_DECIMALS}f}")
    print(f"   Ask: ${ask_price:.{PRICE_DECIMALS}f}")

    # Step 7: Calculate order sizes
    print("\n6. Calculating order sizes...")

    # Base size (fixed - no dynamic sizing to avoid predictable patterns)
    bid_size = BASE_ORDER_SIZE
    ask_size = BASE_ORDER_SIZE

    # Round to valid increments
    bid_size = round(bid_size / SIZE_INCREMENT) * SIZE_INCREMENT
    ask_size = round(ask_size / SIZE_INCREMENT) * SIZE_INCREMENT

    # Enforce minimum
    if bid_size < MIN_ORDER_SIZE:
        bid_size = MIN_ORDER_SIZE
    if ask_size < MIN_ORDER_SIZE:
        ask_size = MIN_ORDER_SIZE

    print(f"   Bid size: {bid_size:.2f} {BASE_TOKEN}")
    print(f"   Ask size: {ask_size:.2f} {BASE_TOKEN}")

    # Step 8: Cancel existing orders
    print("\n7. Cancelling existing orders...")
    num_cancelled = cancel_all_orders()

    # Step 8.5: Refresh balances after cancelling (orders release "hold" funds)
    if num_cancelled > 0:
        print(f"   Refreshing balances after cancellation...")
        try:
            spot_state_refresh = info.post("/info", {
                "type": "spotClearinghouseState",
                "user": account_address
            })
            balances_refresh = spot_state_refresh.get("balances", [])

            for balance_entry in balances_refresh:
                coin_name = balance_entry.get("coin")
                total = float(balance_entry.get("total", "0"))
                hold = float(balance_entry.get("hold", "0"))
                available = total - hold

                if coin_name == BASE_TOKEN:
                    xmr_balance = available
                    position = xmr_balance
                elif coin_name == QUOTE_TOKEN:
                    usdc_balance = available

            print(f"   Updated: {BASE_TOKEN}={xmr_balance:.4f}, {QUOTE_TOKEN}=${usdc_balance:.2f}")
        except Exception as e:
            print(f"   ⚠️  Could not refresh balances: {e}")

    # Step 9: Place new orders (respecting position limits)
    print("\n8. Placing new quotes...")

    bid_placed = False
    ask_placed = False

    # Check balances and position limits before placing
    # Note: In spot, position can range from 0 to MAX_POSITION_SIZE (can't go negative)

    # For BIDS: need USDC and room in position limit
    usdc_needed = bid_size * bid_price
    can_place_bid = (
        position < MAX_POSITION_SIZE and
        position + bid_size <= MAX_POSITION_SIZE and
        usdc_balance >= usdc_needed
    )

    if can_place_bid:
        success, oid = place_quote(is_buy=True, price=bid_price, size=bid_size)
        if success:
            current_bid_oid = oid
            current_bid_price = bid_price
            current_bid_size = bid_size
            print(f"   ✓ Bid posted: {bid_size:.2f} @ ${bid_price:.{PRICE_DECIMALS}f}")
            bid_placed = True
        else:
            current_bid_oid = None
            current_bid_price = None
            print(f"   ✗ Bid failed (see error above)")
            print(f"      Debug: position={position:.4f}, bid_size={bid_size:.2f}, bid_price=${bid_price:.{PRICE_DECIMALS}f}, usdc_balance=${usdc_balance:.2f}")
            bid_placed = False
    else:
        current_bid_oid = None
        current_bid_price = None
        bid_placed = False
        if position >= MAX_POSITION_SIZE:
            print(f"   ⊘ Bid skipped (at max position {MAX_POSITION_SIZE})")
        elif position + bid_size > MAX_POSITION_SIZE:
            print(f"   ⊘ Bid skipped (would exceed max position of {MAX_POSITION_SIZE})")
        elif usdc_balance < usdc_needed:
            print(f"   ⊘ Bid skipped (insufficient {QUOTE_TOKEN}: have ${usdc_balance:.2f}, need ${usdc_needed:.2f})")

    # For ASKS: need XMR1 inventory
    if position >= ask_size:
        success, oid = place_quote(is_buy=False, price=ask_price, size=ask_size)
        if success:
            current_ask_oid = oid
            current_ask_price = ask_price
            current_ask_size = ask_size
            print(f"   ✓ Ask posted: {ask_size:.2f} @ ${ask_price:.{PRICE_DECIMALS}f}")
            ask_placed = True
        else:
            current_ask_oid = None
            current_ask_price = None
            print(f"   ✗ Ask failed (see error above)")
            print(f"      Debug: position={position:.4f}, ask_size={ask_size:.2f}, ask_price=${ask_price:.{PRICE_DECIMALS}f}")
            ask_placed = False
    else:
        current_ask_oid = None
        current_ask_price = None
        ask_placed = False
        print(f"   ⊘ Ask skipped (insufficient {BASE_TOKEN}: have {position:.4f}, need {ask_size:.2f})")

    # Summary
    print(f"\n{'='*80}")
    if bid_placed and ask_placed:
        our_spread = ask_price - bid_price
        our_spread_bps = (our_spread / quoting_mid) * 10000
        print(f"✅ TWO-SIDED MARKET POSTED!")
        print(f"   Spread: ${our_spread:.2f} ({our_spread_bps:.0f} bps)")

        # Compare to anchor
        anchor_to_mid_diff = ((quoting_mid - anchor_price) / anchor_price) * 10000
        print(f"   Mid vs Anchor: {anchor_to_mid_diff:+.0f} bps")
    elif bid_placed or ask_placed:
        print(f"⚠️  ONE-SIDED MARKET (managing position)")
    else:
        print(f"❌ NO QUOTES POSTED")
    print(f"{'='*80}")

    # Update globals for next cycle
    last_spot_mid = spot_mid
    last_inventory = position_total  # Track total (including holds) to avoid false triggers

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    """Main market making loop"""
    # Handle SIGTERM (sent by process.terminate()) gracefully
    # This converts SIGTERM to KeyboardInterrupt so cleanup code runs
    def handle_sigterm(signum, frame):
        print("\nReceived SIGTERM signal...")
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, handle_sigterm)

    print(f"Starting {PAIR_NAME} spot market maker...\n")
    print("Safety features enabled:")
    if PERP_COIN:
        print(f"  - Oracle jump protection: {MAX_ORACLE_JUMP_PCT}%")
    print(f"  - Emergency stop loss: {EMERGENCY_STOP_LOSS_PCT}%")
    print(f"  - Position limit: ±{MAX_POSITION_SIZE} {BASE_TOKEN}")
    print(f"  - Post-only orders (Alo) for maker rebates")
    print("\nPress Ctrl+C to stop\n")

    # Register current configuration and check for changes
    print("📝 Checking bot configuration...")
    current_config = {
        'base_order_size': BASE_ORDER_SIZE,
        'base_spread_bps': BASE_SPREAD_BPS,
        'update_interval_seconds': UPDATE_INTERVAL_SECONDS,
        'update_threshold_bps': CONFIG['timing']['update_threshold_bps'],
        'target_position': TARGET_POSITION,
        'max_position_size': MAX_POSITION_SIZE,
        'inventory_skew_bps_per_unit': INVENTORY_SKEW_BPS_PER_UNIT,
        'max_skew_bps': MAX_SKEW_BPS,
        'inventory_skew_threshold': INVENTORY_SKEW_THRESHOLD,
        'min_ask_buffer_bps': None,
        'max_spot_perp_deviation_pct': CONFIG['safety']['max_spot_perp_deviation_pct'],
        'smart_order_mgmt_enabled': CONFIG['safety']['smart_order_mgmt_enabled'],
    }

    # This will auto-detect changes and log them to parameter_changes table
    changed_id = param_manager.check_for_changes(current_config)
    if changed_id:
        print(f"   ✅ Configuration updated to parameter set #{changed_id}")
    else:
        print(f"   ✅ Using existing parameter set #{param_manager.get_current_id()}")

    # Start metrics capture
    global metrics_capture
    print("📊 Starting metrics capture...")
    metrics_capture = MetricsCapture(PAIR_NAME, get_bot_state_for_metrics)
    metrics_capture.start()
    print()

    # Start WebSocket connection
    global ws_client, use_websocket
    if use_websocket:
        try:
            print("🌐 Initializing WebSocket connection...")
            ws_client = MarketDataWebSocket(
                spot_coin=SPOT_COIN,  # "@260" for both API calls and WebSocket
                account_address=account_address,
                pair_name=PAIR_NAME,  # "PURR/USDC" for fill matching
                update_threshold_bps=CONFIG['timing']['update_threshold_bps'],
                on_update_callback=lambda update_type: None  # Can add logic here if needed
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
    last_quote_update = 0  # Set to 0 to force immediate first update

    try:
        while True:
            iteration += 1

            # Check for rate limit stop
            if rate_limit_hit:
                print("\n🛑 Bot stopped due to rate limiting. Exiting...")
                break

            # Event-driven mode: Wait for WebSocket updates
            if use_websocket and ws_client and ws_client.is_healthy():
                # Block until update or timeout (instant wake-up on price changes!)
                # Use FALLBACK_CHECK_SECONDS as timeout to ensure we check periodically
                ws_client.wait_for_update(timeout=FALLBACK_CHECK_SECONDS)

                # Check what triggered the wake-up
                updates = ws_client.check_updates()

                # Update quotes if something changed or timeout occurred
                time_since_last_update = time.time() - last_quote_update
                should_update = (
                    updates['orderbook'] or  # Market moved >5 bps
                    updates['fills'] or       # Got filled
                    time_since_last_update > FALLBACK_CHECK_SECONDS  # Timeout fallback
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

                        # Check if rate limit was hit during update
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

                # No sleep needed! wait_for_update() blocks until next event

            else:
                # WebSocket unhealthy or disabled - try to reconnect if unhealthy
                if use_websocket and ws_client and not ws_client.is_healthy():
                    print(f"\n⚠️  WebSocket connection unhealthy - attempting reconnection...")
                    if ws_client.reconnect():
                        print(f"   ✅ Reconnected! Resuming event-driven mode")
                        continue  # Skip this iteration, resume event-driven mode
                    else:
                        print(f"   ❌ Reconnection failed, falling back to REST mode")

                # REST-only mode: Use original timing
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

                    # Check if rate limit was hit during update
                    if rate_limit_hit:
                        break
                except Exception as e:
                    print(f"❌ Error in market making loop: {e}")
                    import traceback
                    traceback.print_exc()
                    print("\nContinuing to next iteration...")

                # Check and record fills every iteration
                try:
                    check_and_record_fills()
                except Exception as e:
                    print(f"⚠️  Error checking fills: {e}")

                print(f"\n⏸️  Sleeping {UPDATE_INTERVAL_SECONDS}s...")
                time.sleep(UPDATE_INTERVAL_SECONDS)

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
