#!/usr/bin/env python3
"""
Perp Lobster - Check Market Info
Query Hyperliquid for market decimals, price, and leverage info.

Usage:
  python scripts/check_market.py HYPE
  python scripts/check_market.py ETH
  python scripts/check_market.py xyz:GOLD
  python scripts/check_market.py flx:XMR
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from hyperliquid.info import Info
from hyperliquid.utils import constants

# Known HIP-3 builder dex prefixes
KNOWN_DEXES = ["", "xyz", "flx"]


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_market.py <MARKET_NAME>")
        print("Examples:")
        print("  python scripts/check_market.py HYPE")
        print("  python scripts/check_market.py xyz:GOLD")
        sys.exit(1)

    raw_input = sys.argv[1]

    # Parse dex prefix if present (e.g., "xyz:GOLD" -> dex="xyz", coin="GOLD")
    if ':' in raw_input:
        dex, coin = raw_input.split(':', 1)
        dex = dex.lower()
        coin = coin.upper()
        market_name = f"{dex}:{coin}"
    else:
        dex = ""
        coin = raw_input.upper()
        market_name = coin

    info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=KNOWN_DEXES)

    def estimate_decimals(price):
        if price >= 10000: return 1
        elif price >= 1000: return 2
        elif price >= 100: return 3
        elif price >= 10: return 3
        elif price >= 1: return 4
        else: return 5

    if dex:
        # HIP-3: meta_and_asset_ctxs() doesn't support dex param,
        # so use meta(dex=) + all_mids(dex=) instead
        hip3_meta = info.meta(dex=dex)
        hip3_universe = hip3_meta.get('universe', [])
        mids = info.all_mids(dex=dex)

        for asset in hip3_universe:
            asset_name = asset['name']
            # SDK may return "SILVER" or "xyz:SILVER" — match either way
            asset_bare = asset_name.split(':')[-1] if ':' in asset_name else asset_name
            if asset_bare.upper() == coin.upper() or asset_name.upper() == market_name.upper():
                # Get mid price (mids keys may also be bare or prefixed)
                mid_price = None
                for mid_coin, mid_val in mids.items():
                    mid_bare = mid_coin.split(':')[-1] if ':' in mid_coin else mid_coin
                    if mid_bare.upper() == coin.upper():
                        mid_price = float(mid_val)
                        break

                full_name = f"{dex}:{asset_bare}" if ':' not in asset_name else asset_name
                print(f"Asset: {full_name}")
                if mid_price:
                    print(f"Mid price: {mid_price}")
                    print(f"Suggested price_decimals: {estimate_decimals(mid_price)}")
                else:
                    print(f"Mid price: N/A (market may be inactive)")
                print(f"Size decimals: {asset.get('szDecimals', 2)}")
                print(f"Max leverage: {asset.get('maxLeverage', 3)}")
                print(f"Dex: {dex}")
                print(f"\nFor your config file, set:")
                print(f'  "market": "{full_name}"')
                print(f'  "dex": "{dex}"')
                if mid_price:
                    print(f'  "exchange.price_decimals": {estimate_decimals(mid_price)}')
                print(f'  "exchange.size_decimals": {asset.get("szDecimals", 2)}')
                return

        print(f"Market '{market_name}' not found on dex '{dex}'")
        # List available markets on this dex
        if hip3_universe:
            names = [a['name'] for a in hip3_universe[:20]]
            print(f"\nAvailable on {dex}: {', '.join(names)}")
            if len(hip3_universe) > 20:
                print(f"  ... and {len(hip3_universe) - 20} more")
        sys.exit(1)

    # Standard markets: meta_and_asset_ctxs includes markPx
    meta = info.meta_and_asset_ctxs()
    universe = meta[0]['universe']

    for i, asset in enumerate(universe):
        name = asset['name']
        if name.upper() == coin.upper():
            ctx = meta[1][i]
            mark = float(ctx['markPx'])

            print(f"Asset: {name}")
            print(f"Mark price: {mark}")
            print(f"Suggested price_decimals: {estimate_decimals(mark)}")
            print(f"Size decimals: {asset.get('szDecimals', 2)}")
            print(f"Max leverage: {asset.get('maxLeverage', 3)}")
            return

    print(f"Market '{market_name}' not found on Hyperliquid")
    print(f"\nSearched across dexes: {', '.join(d or '(standard)' for d in KNOWN_DEXES)}")
    sys.exit(1)


if __name__ == '__main__':
    main()
