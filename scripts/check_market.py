#!/usr/bin/env python3
"""
Perp Lobster - Check Market Info
Query Hyperliquid for market decimals, price, and leverage info.

Usage:
  python scripts/check_market.py HYPE
  python scripts/check_market.py ETH
  python scripts/check_market.py BTC
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from hyperliquid.info import Info
from hyperliquid.utils import constants


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_market.py <MARKET_NAME>")
        print("Example: python scripts/check_market.py HYPE")
        sys.exit(1)

    market_name = sys.argv[1].upper()
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    meta = info.meta_and_asset_ctxs()
    universe = meta[0]['universe']

    for i, asset in enumerate(universe):
        if asset['name'].upper() == market_name:
            ctx = meta[1][i]
            mark = float(ctx['markPx'])
            if mark >= 10000:
                decimals = 1
            elif mark >= 1000:
                decimals = 2
            elif mark >= 100:
                decimals = 3
            elif mark >= 10:
                decimals = 3
            elif mark >= 1:
                decimals = 4
            else:
                decimals = 5
            print(f"Asset: {asset['name']}")
            print(f"Mark price: {mark}")
            print(f"Suggested price_decimals: {decimals}")
            print(f"Size decimals: {asset.get('szDecimals', 2)}")
            print(f"Max leverage: {asset.get('maxLeverage', 3)}")
            return

    print(f"Market '{market_name}' not found on Hyperliquid")
    sys.exit(1)


if __name__ == '__main__':
    main()
