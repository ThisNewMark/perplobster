#!/usr/bin/env python3
"""
Perp Lobster - Simple Trade Execution
Place one-time market or limit orders on Hyperliquid perps.

Usage:
  python scripts/trade.py long HYPE 50
  python scripts/trade.py short ETH 100
  python scripts/trade.py long HYPE 50 --price 29.50
  python scripts/trade.py short ETH 100 --price 1900 --subaccount 0x...
  python scripts/trade.py close HYPE
  python scripts/trade.py long xyz:GOLD 50          # HIP-3 builder market
  python scripts/trade.py short flx:XMR 100         # HIP-3 builder market
  python scripts/trade.py close xyz:GOLD             # Close HIP-3 position
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from credentials import get_credentials, get_builder, ensure_builder_fee_approved

# Known HIP-3 builder dex prefixes
KNOWN_DEXES = ["", "xyz", "flx"]


def parse_market_name(raw_name):
    """Parse market input, handling HIP-3 dex:COIN format.

    Returns:
        (market_name, dex) - e.g. ("xyz:GOLD", "xyz") or ("HYPE", "")
    """
    if ':' in raw_name:
        dex, coin = raw_name.split(':', 1)
        return f"{dex.lower()}:{coin.upper()}", dex.lower()
    return raw_name.upper(), ""


def estimate_price_decimals(price):
    """Estimate appropriate price decimals from a price value."""
    if price >= 10000:
        return 1
    elif price >= 1000:
        return 2
    elif price >= 100:
        return 3
    elif price >= 10:
        return 3
    elif price >= 1:
        return 4
    else:
        return 5


def get_asset_info(info, market_name, dex=""):
    """Get price decimals and size decimals for an asset.

    For standard markets, uses meta_and_asset_ctxs() which includes markPx.
    For HIP-3 builder markets, uses meta(dex=) + all_mids(dex=) since
    meta_and_asset_ctxs() only returns the standard dex.
    """
    if dex:
        # HIP-3: meta_and_asset_ctxs() doesn't support dex param,
        # so fetch metadata and mids separately
        hip3_meta = info.meta(dex=dex)
        hip3_universe = hip3_meta.get('universe', [])
        coin = market_name.split(':', 1)[1] if ':' in market_name else market_name
        for asset in hip3_universe:
            asset_name = asset['name']
            # SDK may return "SILVER" or "xyz:SILVER" — match either way
            asset_bare = asset_name.split(':')[-1] if ':' in asset_name else asset_name
            if asset_bare.upper() == coin.upper() or asset_name.upper() == market_name.upper():
                # Get mid price from all_mids (keys may also be bare or prefixed)
                mids = info.all_mids(dex=dex)
                mid_price = None
                for mid_coin, mid_val in mids.items():
                    mid_bare = mid_coin.split(':')[-1] if ':' in mid_coin else mid_coin
                    if mid_bare.upper() == coin.upper():
                        mid_price = float(mid_val)
                        break
                if mid_price is None or mid_price == 0:
                    print(f"  Warning: No mid price for {market_name}, market may be inactive")
                    return None
                full_name = f"{dex}:{asset_bare}" if ':' not in asset_name else asset_name
                return {
                    'name': full_name,
                    'mark_price': mid_price,
                    'price_decimals': estimate_price_decimals(mid_price),
                    'size_decimals': asset.get('szDecimals', 2),
                    'max_leverage': asset.get('maxLeverage', 3),
                }
        return None

    # Standard markets: meta_and_asset_ctxs includes markPx
    meta = info.meta_and_asset_ctxs()
    universe = meta[0]['universe']
    for i, asset in enumerate(universe):
        if asset['name'].upper() == market_name.upper():
            ctx = meta[1][i]
            mark = float(ctx['markPx'])
            return {
                'name': asset['name'],
                'mark_price': mark,
                'price_decimals': estimate_price_decimals(mark),
                'size_decimals': asset.get('szDecimals', 2),
                'max_leverage': asset.get('maxLeverage', 3),
            }
    return None


def main():
    parser = argparse.ArgumentParser(description='Perp Lobster - Place trades on Hyperliquid')
    parser.add_argument('action', choices=['long', 'short', 'close'], help='Trade action')
    parser.add_argument('market', help='Market name (e.g., HYPE, ETH, xyz:GOLD, flx:XMR)')
    parser.add_argument('size_usd', nargs='?', type=float, default=None, help='Order size in USD (not needed for close)')
    parser.add_argument('--price', type=float, default=None, help='Limit price (omit for market order)')
    parser.add_argument('--subaccount', type=str, default=None, help='Subaccount address')
    parser.add_argument('--leverage', type=int, default=None, help='Set leverage before trading')
    parser.add_argument('--reduce-only', action='store_true', help='Reduce-only order')

    args = parser.parse_args()

    if args.action != 'close' and args.size_usd is None:
        parser.error("size_usd is required for long/short orders")

    # Parse market name (handles HIP-3 dex:COIN format)
    market_name, dex = parse_market_name(args.market)
    is_hip3 = dex != ""

    # Load credentials
    creds = get_credentials()
    if not creds.get('secret_key'):
        print("Error: No credentials found. Edit .env with your HL_ACCOUNT_ADDRESS and HL_SECRET_KEY")
        sys.exit(1)

    secret_key = creds['secret_key']
    account_address = creds.get('account_address')
    account = Account.from_key(secret_key)

    # Setup API (include perp_dexs for HIP-3 builder market support)
    info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=KNOWN_DEXES)
    vault_address = args.subaccount if args.subaccount else None
    exchange = Exchange(
        wallet=account,
        base_url=constants.MAINNET_API_URL,
        vault_address=vault_address,
        account_address=account_address,
        perp_dexs=KNOWN_DEXES
    )

    # Auto-approve builder fee
    ensure_builder_fee_approved(exchange)

    # Get asset info
    asset_info = get_asset_info(info, market_name, dex=dex)
    if not asset_info:
        print(f"Error: Market '{market_name}' not found on Hyperliquid")
        if not is_hip3:
            print(f"  For HIP-3 builder markets, use format: xyz:GOLD or flx:XMR")
        else:
            print(f"  Check the ticker is correct on https://app.hyperliquid.xyz/trade/{market_name}")
        sys.exit(1)

    market = asset_info['name']
    mark_price = asset_info['mark_price']
    price_dec = asset_info['price_decimals']
    size_dec = asset_info['size_decimals']

    print(f"\n{'='*50}")
    print(f"  Perp Lobster - {args.action.upper()} {market}")
    print(f"{'='*50}")
    print(f"  Mark price: ${mark_price}")
    if is_hip3:
        print(f"  Market type: HIP-3 builder ({dex})")
    if args.subaccount:
        print(f"  Subaccount: {args.subaccount[:10]}...")

    # Set leverage if requested
    if args.leverage:
        try:
            exchange.update_leverage(args.leverage, market, is_cross=False)
            print(f"  Leverage: {args.leverage}x")
        except Exception as e:
            print(f"  Leverage note: {e}")

    # Handle close
    if args.action == 'close':
        print(f"\n  Closing position on {market}...")
        result = exchange.market_close(market, builder=get_builder())
        if result and result.get('status') == 'ok':
            print(f"  Position closed successfully!")
        else:
            print(f"  Close result: {result}")
        return

    # Calculate size in contracts
    size_contracts = round(args.size_usd / mark_price, size_dec)
    is_buy = args.action == 'long'
    builder = get_builder()

    if args.price:
        # Limit order
        price = round(args.price, price_dec)
        order_type = {"limit": {"tif": "Gtc"}}  # Good til cancelled
        print(f"  Type: LIMIT")
        print(f"  Price: ${price}")
        print(f"  Size: {size_contracts} contracts (~${args.size_usd})")
        print(f"{'='*50}\n")

        result = exchange.order(market, is_buy, size_contracts, price, order_type, args.reduce_only, builder=builder)
    else:
        # Market order (IOC at extreme price)
        if is_buy:
            extreme_price = round(mark_price * 1.05, price_dec)  # 5% above market
        else:
            extreme_price = round(mark_price * 0.95, price_dec)  # 5% below market

        order_type = {"limit": {"tif": "Ioc"}}  # Immediate or cancel
        print(f"  Type: MARKET")
        print(f"  Size: {size_contracts} contracts (~${args.size_usd})")
        print(f"{'='*50}\n")

        result = exchange.order(market, is_buy, size_contracts, extreme_price, order_type, args.reduce_only, builder=builder)

    # Parse result
    if result.get('status') == 'ok':
        statuses = result.get('response', {}).get('data', {}).get('statuses', [])
        if statuses:
            status = statuses[0]
            if 'resting' in status:
                oid = status['resting']['oid']
                print(f"  Limit order placed! OID: {oid}")
            elif 'filled' in status:
                fill = status['filled']
                print(f"  Filled! Price: ${fill.get('avgPx', 'N/A')}, Size: {fill.get('totalSz', 'N/A')}")
            else:
                print(f"  Order status: {status}")
        else:
            print(f"  Order submitted successfully")
    else:
        print(f"  Order error: {result}")


if __name__ == '__main__':
    main()
