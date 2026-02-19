"""
Config Discovery Module
Auto-discovers all trading pair configs from the config directory
"""

import os
import json
from typing import List, Dict, Optional


class ConfigDiscovery:
    """Discover and manage trading pair configurations"""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir

    def get_all_pairs(self) -> List[Dict]:
        """
        Get all trading pair configurations (spot and perp)

        Returns:
            List of dicts with pair info: {
                'pair': 'XMR1/USDC' or 'ICP-PERP',
                'type': 'spot' or 'perp',
                'config_file': 'config/xmr_config.json',
                'route': 'xmr1' or 'icp-perp',
                'base_token': 'XMR1' or 'ICP',
                'quote_token': 'USDC' or None (for perps)
            }
        """
        pairs = []

        if not os.path.exists(self.config_dir):
            return pairs

        # Scan config directory for JSON files
        for filename in os.listdir(self.config_dir):
            if not filename.endswith('.json') or filename == 'config.json':
                continue

            filepath = os.path.join(self.config_dir, filename)

            try:
                with open(filepath, 'r') as f:
                    config = json.load(f)

                # Check if it's a spot config (has 'pair'), grid config (has 'grid'), or perp config (has 'market')
                pair_name = config.get('pair')
                market_name = config.get('market')
                has_grid = 'grid' in config

                if pair_name:
                    # Spot config
                    if '/' in pair_name:
                        base_token, quote_token = pair_name.split('/')
                    else:
                        continue

                    route = base_token.lower()

                    pairs.append({
                        'pair': pair_name,
                        'type': 'spot',
                        'config_file': filepath,
                        'route': route,
                        'base_token': base_token,
                        'quote_token': quote_token,
                        'description': config.get('description', f'{pair_name} trading'),
                        'spot_coin': config.get('exchange', {}).get('spot_coin'),
                        'is_subaccount': config.get('account', {}).get('is_subaccount', False),
                        'subaccount_address': config.get('account', {}).get('subaccount_address')
                    })

                elif has_grid and market_name:
                    # Grid config - treat similar to perp but mark as grid type
                    # Clean market name (remove dex prefix like "xyz:")
                    clean_market = market_name.split(':')[-1] if ':' in market_name else market_name
                    display_name = f"{clean_market}-GRID"
                    route = f"{clean_market.lower()}-grid"

                    pairs.append({
                        'pair': display_name,
                        'type': 'grid',
                        'config_file': filepath,
                        'route': route,
                        'base_token': clean_market,
                        'quote_token': None,
                        'market_name': market_name,  # Keep original for bot
                        'description': config.get('description', f'{clean_market} grid trading'),
                        'is_subaccount': config.get('account', {}).get('is_subaccount', False),
                        'subaccount_address': config.get('account', {}).get('subaccount_address'),
                        'leverage': config.get('position', {}).get('leverage', 1),
                        'max_position_usd': config.get('position', {}).get('max_position_usd', 0)
                    })

                elif market_name:
                    # Perp config
                    display_name = f"{market_name}-PERP"
                    route = f"{market_name.lower()}-perp"

                    pairs.append({
                        'pair': display_name,
                        'type': 'perp',
                        'config_file': filepath,
                        'route': route,
                        'base_token': market_name,
                        'quote_token': None,  # Perps don't have quote token
                        'market_name': market_name,
                        'description': config.get('description', f'{market_name} perpetual trading'),
                        'is_subaccount': config.get('account', {}).get('is_subaccount', False),
                        'subaccount_address': config.get('account', {}).get('subaccount_address'),
                        'leverage': config.get('position', {}).get('leverage', 5),
                        'max_position_usd': config.get('position', {}).get('max_position_usd', 0)
                    })

            except Exception as e:
                print(f"Warning: Could not load config {filename}: {e}")
                continue

        # Sort by pair name
        pairs.sort(key=lambda x: x['pair'])

        return pairs

    def get_pair_config(self, route: str) -> Optional[Dict]:
        """
        Get configuration for a specific pair by route

        Args:
            route: Route name like 'xmr1', 'kntq', 'purr'

        Returns:
            Full config dict or None
        """
        pairs = self.get_all_pairs()

        for pair_info in pairs:
            if pair_info['route'] == route.lower():
                # Load full config
                with open(pair_info['config_file'], 'r') as f:
                    return json.load(f)

        return None

    def get_pair_info(self, route: str) -> Optional[Dict]:
        """
        Get pair info (not full config) by route

        Args:
            route: Route name like 'xmr1', 'kntq', 'purr'

        Returns:
            Pair info dict or None
        """
        pairs = self.get_all_pairs()

        for pair_info in pairs:
            if pair_info['route'] == route.lower():
                return pair_info

        return None


if __name__ == '__main__':
    # Test
    discovery = ConfigDiscovery()
    pairs = discovery.get_all_pairs()

    print(f"Found {len(pairs)} trading pairs:")
    for pair in pairs:
        print(f"  - {pair['pair']:12s} (route: /{pair['route']}, file: {pair['config_file']})")
        if pair['is_subaccount']:
            print(f"    Subaccount: {pair['subaccount_address'][:10]}...")
