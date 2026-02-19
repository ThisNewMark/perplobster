"""
Configuration Loader
Loads and validates bot configuration from JSON files
"""

import json
import os
from typing import Dict, Any

class ConfigLoader:
    """Loads bot configuration from JSON files"""

    @staticmethod
    def load(config_path: str) -> Dict[str, Any]:
        """
        Load configuration from JSON file

        Args:
            config_path: Path to config JSON file

        Returns:
            Configuration dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            config = json.load(f)

        # Clean up subaccount address (strip HL: prefix if present)
        # Users may paste addresses from Hyperliquid UI which includes "HL:" prefix
        if 'account' in config and 'subaccount_address' in config['account']:
            addr = config['account']['subaccount_address']
            if addr and isinstance(addr, str):
                # Strip "HL:" or "hl:" prefix if present
                if addr.upper().startswith('HL:'):
                    config['account']['subaccount_address'] = addr[3:]

        # Validate required sections (flexible for spot and perp configs)
        # Spot configs have 'pair', perp configs have 'market'
        if 'pair' not in config and 'market' not in config:
            raise ValueError("Config must have either 'pair' (spot) or 'market' (perp)")

        required_sections = ['trading', 'position', 'timing', 'safety']
        for section in required_sections:
            if section not in config:
                raise ValueError(f"Missing required config section: {section}")

        return config

    @staticmethod
    def get(config: Dict, *keys, default=None):
        """
        Safely get nested config value

        Args:
            config: Configuration dictionary
            *keys: Path to value (e.g., 'trading', 'base_spread_bps')
            default: Default value if key not found

        Returns:
            Config value or default

        Example:
            get(config, 'trading', 'base_spread_bps', default=50)
        """
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    @staticmethod
    def validate_trading_config(config: Dict) -> bool:
        """
        Validate trading configuration

        Args:
            config: Configuration dictionary

        Returns:
            True if valid

        Raises:
            ValueError: If configuration is invalid
        """
        trading = config.get('trading', {})

        # Validate spread settings
        base_spread = trading.get('base_spread_bps')
        min_spread = trading.get('min_spread_bps')
        max_spread = trading.get('max_spread_bps')

        if base_spread and min_spread and base_spread < min_spread:
            raise ValueError(f"base_spread_bps ({base_spread}) cannot be less than min_spread_bps ({min_spread})")

        if base_spread and max_spread and base_spread > max_spread:
            raise ValueError(f"base_spread_bps ({base_spread}) cannot be greater than max_spread_bps ({max_spread})")

        # Validate order size
        order_size = trading.get('base_order_size')
        if order_size and order_size <= 0:
            raise ValueError(f"base_order_size must be positive, got {order_size}")

        # Validate position limits (handle both spot and perp formats)
        position = config.get('position', {})

        # Spot bot uses max_position_size/target_position
        # Perp bot uses max_position_usd/target_position_usd
        max_pos = position.get('max_position_size') or position.get('max_position_usd')
        target_pos = position.get('target_position') or position.get('target_position_usd')

        if max_pos and target_pos is not None and abs(target_pos) > max_pos:
            raise ValueError(f"target_position ({target_pos}) cannot exceed max_position ({max_pos})")

        return True
