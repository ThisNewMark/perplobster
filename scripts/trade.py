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
  python scripts/trade.py close HYPE --subaccount 0x...
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


def get_asset_info(info, asset_name):
    """Get price decimals and size decimals for an asset."""
    meta = info.meta_and_asset_ctxs()
    universe = meta[0]['universe']
    for i, asset in enumerate(universe):
        if asset['name'].upper() == asset_name.upper():
            ctx = meta[1][i]
            mark = float(ctx['markPx'])
            if mark >= 10000:
                price_dec = 1
            elif mark >= 1000:
                price_dec = 2
            elif mark >= 100:
                price_dec = 3
            elif mark >= 10:
                price_dec = 3
            elif mark >= 1:
                price_dec = 4
            else:
                price_dec = 5
            return {
                'name': asset['name'],
                'mark_price': mark,
                'price_decimals': price_dec,
                'size_decimals': asset.get('szDecimals', 2),
                'max_leverage': asset.get('maxLeverage', 3),
            }
    return None


def main():
    parser = argparse.ArgumentParser(description='Perp Lobster - Place trades on Hyperliquid')
    parser.add_argument('action', choices=['long', 'short', 'close'], help='Trade action')
    parser.add_argument('market', help='Market name (e.g., HYPE, ETH, BTC)')
    parser.add_argument('size_usd', nargs='?', type=float, default=None, help='Order size in USD (not needed for close)')
    parser.add_argument('--price', type=float, default=None, help='Limit price (omit for market order)')
    parser.add_argument('--subaccount', type=str, default=None, help='Subaccount address')
    parser.add_argument('--leverage', type=int, default=None, help='Set leverage before trading')
    parser.add_argument('--reduce-only', action='store_true', help='Reduce-only order')

    args = parser.parse_args()

    if args.action != 'close' and args.size_usd is None:
        parser.error("size_usd is required for long/short orders")

    # Load credentials
    creds = get_credentials()
    if not creds.get('secret_key'):
        print("Error: No credentials found. Edit .env with your HL_ACCOUNT_ADDRESS and HL_SECRET_KEY")
        sys.exit(1)

    secret_key = creds['secret_key']
    account_address = creds.get('account_address')
    account = Account.from_key(secret_key)

    # Setup API
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    vault_address = args.subaccount if args.subaccount else None
    exchange = Exchange(
        wallet=account,
        base_url=constants.MAINNET_API_URL,
        vault_address=vault_address,
        account_address=account_address
    )

    # Auto-approve builder fee
    ensure_builder_fee_approved(exchange)

    # Get asset info
    asset_info = get_asset_info(info, args.market)
    if not asset_info:
        print(f"Error: Market '{args.market}' not found on Hyperliquid")
        sys.exit(1)

    market = asset_info['name']
    mark_price = asset_info['mark_price']
    price_dec = asset_info['price_decimals']
    size_dec = asset_info['size_decimals']

    print(f"\n{'='*50}")
    print(f"  Perp Lobster - {args.action.upper()} {market}")
    print(f"{'='*50}")
    print(f"  Mark price: ${mark_price}")
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
