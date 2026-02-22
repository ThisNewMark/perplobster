#!/usr/bin/env python3
"""
Perp Lobster - Config Generator
Auto-generates bot config files with correct market decimals.

Usage:
  python scripts/create_config.py mm HYPE                     # Perp market maker with defaults
  python scripts/create_config.py mm UNI --spread 80          # Perp MM with 80 bps spread
  python scripts/create_config.py mm xyz:SILVER --spread 50   # HIP-3 perp MM
  python scripts/create_config.py grid xyz:COPPER             # Grid trader
  python scripts/create_config.py grid HYPE --bias long       # Grid with long bias
  python scripts/create_config.py mm UNI --size 25 --max-pos 200 --leverage 5
  python scripts/create_config.py mm UNI -o config/uni_mm.json  # Custom output path
"""

import argparse
import json
import sys
import os
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from hyperliquid.info import Info
from hyperliquid.utils import constants

KNOWN_DEXES = ["", "xyz", "flx"]
EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), '..', 'config', 'examples')
CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'config')


def parse_market(raw):
    if ':' in raw:
        dex, coin = raw.split(':', 1)
        return f"{dex.lower()}:{coin.upper()}", dex.lower(), coin.upper()
    return raw.upper(), "", raw.upper()


def get_market_data(market_name, dex):
    """Fetch price and decimals from Hyperliquid."""
    info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=KNOWN_DEXES)

    if dex:
        meta = info.meta(dex=dex)
        universe = meta.get('universe', [])
        coin = market_name.split(':')[-1]
        mids = info.all_mids(dex=dex)

        for asset in universe:
            asset_bare = asset['name'].split(':')[-1] if ':' in asset['name'] else asset['name']
            if asset_bare.upper() == coin.upper():
                mid_price = None
                for k, v in mids.items():
                    k_bare = k.split(':')[-1] if ':' in k else k
                    if k_bare.upper() == coin.upper():
                        mid_price = float(v)
                        break
                return {
                    'price': mid_price or 0,
                    'size_decimals': asset.get('szDecimals', 2),
                    'max_leverage': asset.get('maxLeverage', 3),
                }
        return None

    meta = info.meta_and_asset_ctxs()
    universe = meta[0]['universe']
    for i, asset in enumerate(universe):
        if asset['name'].upper() == market_name.upper():
            ctx = meta[1][i]
            return {
                'price': float(ctx['markPx']),
                'size_decimals': asset.get('szDecimals', 2),
                'max_leverage': asset.get('maxLeverage', 3),
            }
    return None


def estimate_price_decimals(price):
    if price >= 10000: return 1
    elif price >= 1000: return 2
    elif price >= 100: return 3
    elif price >= 10: return 3
    elif price >= 1: return 4
    else: return 5


def main():
    parser = argparse.ArgumentParser(
        description='Generate a bot config with correct market decimals',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n'
               '  python scripts/create_config.py mm HYPE\n'
               '  python scripts/create_config.py mm UNI --spread 80\n'
               '  python scripts/create_config.py mm xyz:SILVER --spread 50 --size 20\n'
               '  python scripts/create_config.py grid xyz:COPPER --bias long\n'
    )
    parser.add_argument('strategy', choices=['mm', 'grid'],
                        help='Bot type: mm (perp market maker) or grid (grid trader)')
    parser.add_argument('market', help='Market name (e.g., HYPE, UNI, xyz:SILVER)')
    parser.add_argument('--spread', type=float, default=None,
                        help='Base spread in bps (default: 15 for mm, N/A for grid)')
    parser.add_argument('--size', type=float, default=None,
                        help='Order size in USD (default: 15 for mm, 25 for grid)')
    parser.add_argument('--max-pos', type=float, default=None,
                        help='Max position in USD (default: 100)')
    parser.add_argument('--leverage', type=int, default=None,
                        help='Leverage (default: 3)')
    parser.add_argument('--bias', choices=['long', 'short', 'neutral'], default='neutral',
                        help='Grid bias (grid only, default: neutral)')
    parser.add_argument('--levels', type=int, default=5,
                        help='Grid levels each side (grid only, default: 5)')
    parser.add_argument('--spacing', type=float, default=0.5,
                        help='Grid spacing %% (grid only, default: 0.5)')
    parser.add_argument('-o', '--output', type=str, default=None,
                        help='Output file path (default: config/<market>_<strategy>.json)')

    args = parser.parse_args()

    market_name, dex, coin = parse_market(args.market)

    # Fetch market data
    print(f"Checking {market_name} on Hyperliquid...")
    data = get_market_data(market_name, dex)
    if not data:
        print(f"Error: Market '{market_name}' not found")
        if not dex:
            print("  For HIP-3 builder markets, use format: xyz:GOLD")
        sys.exit(1)

    price = data['price']
    size_dec = data['size_decimals']
    price_dec = estimate_price_decimals(price)
    max_lev = data['max_leverage']

    print(f"  Price: ${price}")
    print(f"  Price decimals: {price_dec}")
    print(f"  Size decimals: {size_dec}")
    print(f"  Max leverage: {max_lev}x")

    # Load example config
    if args.strategy == 'mm':
        example_path = os.path.join(EXAMPLES_DIR, 'perp_example.json')
    else:
        example_path = os.path.join(EXAMPLES_DIR, 'grid_example.json')

    with open(example_path, 'r') as f:
        config = json.load(f)

    # Fill in market-specific values
    config['market'] = market_name
    config['dex'] = dex
    config['exchange']['price_decimals'] = price_dec
    config['exchange']['size_decimals'] = size_dec

    # Remove comment fields for clean output
    for key in list(config.keys()):
        if key.startswith('_comment'):
            del config[key]
    for section in config.values():
        if isinstance(section, dict):
            for key in list(section.keys()):
                if key.startswith('_comment'):
                    del section[key]

    leverage = args.leverage or min(3, max_lev)
    config['position']['leverage'] = leverage

    if args.max_pos:
        config['position']['max_position_usd'] = args.max_pos

    if args.strategy == 'mm':
        config['description'] = f"Perp market maker for {market_name}"
        if args.spread:
            config['trading']['base_spread_bps'] = args.spread
            config['trading']['min_spread_bps'] = max(5, args.spread * 0.5)
        if args.size:
            config['trading']['base_order_size'] = args.size

        # Calculate min_order_size based on price — $1 worth at minimum
        # This prevents silently dropping orders on expensive assets
        if price > 0:
            min_size = round(1.0 / price, size_dec)
            # Ensure it's at least one unit at the smallest decimal
            min_size = max(min_size, 10 ** -size_dec)
            config['trading']['min_order_size'] = min_size
    else:
        config['description'] = f"Grid trader for {market_name}"
        config['grid']['bias'] = args.bias
        config['grid']['num_levels_each_side'] = args.levels
        config['grid']['spacing_pct'] = args.spacing
        if args.size:
            config['grid']['order_size_usd'] = args.size

    # Determine output path
    if args.output:
        out_path = args.output
    else:
        safe_name = coin.lower()
        out_path = os.path.join(CONFIG_DIR, f"{safe_name}_{args.strategy}.json")

    # Check if file exists
    if os.path.exists(out_path):
        print(f"\n  Warning: {out_path} already exists!")
        # Don't overwrite — let Claude or the user decide
        base, ext = os.path.splitext(out_path)
        i = 2
        while os.path.exists(f"{base}_{i}{ext}"):
            i += 1
        out_path = f"{base}_{i}{ext}"
        print(f"  Saving to {out_path} instead")

    # Write config
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"\nConfig saved: {out_path}")
    print(f"\nTo start the bot:")
    print(f"  ./start.sh {out_path}")
    print(f"\nKey settings:")
    if args.strategy == 'mm':
        print(f"  Spread: {config['trading']['base_spread_bps']} bps")
        print(f"  Order size: ${config['trading']['base_order_size']}")
    else:
        print(f"  Grid spacing: {config['grid']['spacing_pct']}%")
        print(f"  Order size: ${config['grid']['order_size_usd']}")
        print(f"  Levels: {config['grid']['num_levels_each_side']} each side")
        print(f"  Bias: {config['grid']['bias']}")
    print(f"  Max position: ${config['position']['max_position_usd']}")
    print(f"  Leverage: {leverage}x")


if __name__ == '__main__':
    main()
