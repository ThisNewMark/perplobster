"""
Parameter Set Manager
Handles bot configuration versioning and tracking
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Optional, Any

DATABASE_PATH = "trading_data.db"

class ParameterManager:
    """Manages bot configuration versions and changes"""

    def __init__(self, pair: str):
        self.pair = pair
        self.current_param_set_id = None

        # Load last used parameter set ID from database
        self._load_last_param_set_id()

    def register_config(self, config: Dict[str, Any], description: str = None) -> int:
        """
        Register a configuration and return its parameter_set_id

        Args:
            config: Dictionary of configuration parameters
            description: Optional human-readable description

        Returns:
            parameter_set_id (int)
        """
        # Add pair to config
        config_with_pair = {**config, 'pair': self.pair}

        # Calculate hash
        config_hash = self._calculate_hash(config_with_pair)

        # Check if this exact config already exists
        existing_id = self._find_existing_config(config_hash)

        if existing_id:
            print(f"   Using existing parameter set #{existing_id}")
            return existing_id

        # Insert new config
        param_set_id = self._insert_config(config_with_pair, config_hash, description)
        print(f"   Created new parameter set #{param_set_id}")

        return param_set_id

    def log_change(
        self,
        new_param_set_id: int,
        old_param_set_id: Optional[int] = None,
        reason: str = 'manual',
        notes: str = ''
    ):
        """
        Log a parameter change

        Args:
            new_param_set_id: ID of new configuration
            old_param_set_id: ID of previous configuration (optional)
            reason: Why the change was made ('manual', 'auto', 'emergency')
            notes: Additional notes
        """
        # Get configs to generate change summary
        old_config = self._get_config(old_param_set_id) if old_param_set_id else None
        new_config = self._get_config(new_param_set_id)

        change_summary = self._generate_change_summary(old_config, new_config)
        change_type = self._determine_change_type(old_config, new_config)

        # Insert change log
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO parameter_changes
                (pair, old_parameter_set_id, new_parameter_set_id,
                 change_type, change_summary, reason, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self.pair,
                old_param_set_id,
                new_param_set_id,
                change_type,
                change_summary,
                reason,
                notes
            ))
            conn.commit()

            print(f"   📝 Logged parameter change: {change_summary}")

        finally:
            cursor.close()
            conn.close()

    def check_for_changes(self, current_config: Dict[str, Any]) -> Optional[int]:
        """
        Check if configuration has changed since last registration

        Args:
            current_config: Current bot configuration

        Returns:
            New parameter_set_id if changed, None if unchanged
        """
        new_param_set_id = self.register_config(current_config)

        if self.current_param_set_id is None:
            # First run
            self.current_param_set_id = new_param_set_id
            self.log_change(
                new_param_set_id=new_param_set_id,
                reason='auto',
                notes='Bot started'
            )
            return new_param_set_id

        if new_param_set_id != self.current_param_set_id:
            # Config changed
            self.log_change(
                new_param_set_id=new_param_set_id,
                old_param_set_id=self.current_param_set_id,
                reason='auto',
                notes='Configuration change detected'
            )
            old_id = self.current_param_set_id
            self.current_param_set_id = new_param_set_id
            return new_param_set_id

        # No change
        return None

    def get_current_id(self) -> Optional[int]:
        """Get current parameter_set_id"""
        return self.current_param_set_id

    # ========== Private Methods ==========

    def _calculate_hash(self, config: Dict[str, Any]) -> str:
        """Calculate SHA256 hash of configuration"""
        # Sort keys for consistent hashing
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()

    def _find_existing_config(self, config_hash: str) -> Optional[int]:
        """Check if config with this hash already exists"""
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT id FROM parameter_sets
                WHERE pair = ? AND config_hash = ?
            """, (self.pair, config_hash))

            result = cursor.fetchone()
            return result[0] if result else None

        finally:
            cursor.close()
            conn.close()

    def _insert_config(
        self,
        config: Dict[str, Any],
        config_hash: str,
        description: Optional[str]
    ) -> int:
        """Insert new configuration and return its ID"""
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO parameter_sets
                (pair, config_hash, base_order_size, base_spread_bps,
                 update_interval_seconds, update_threshold_bps,
                 target_position, max_position_size,
                 inventory_skew_bps_per_unit, max_skew_bps,
                 inventory_skew_threshold, min_ask_buffer_bps,
                 max_spot_perp_deviation_pct, smart_order_mgmt_enabled,
                 description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
            """, (
                self.pair,
                config_hash,
                config.get('base_order_size'),
                config.get('base_spread_bps'),
                config.get('update_interval_seconds'),
                config.get('update_threshold_bps'),
                config.get('target_position'),
                config.get('max_position_size'),
                config.get('inventory_skew_bps_per_unit'),
                config.get('max_skew_bps'),
                config.get('inventory_skew_threshold'),
                config.get('min_ask_buffer_bps'),
                config.get('max_spot_perp_deviation_pct'),
                config.get('smart_order_mgmt_enabled', False),
                description
            ))

            param_set_id = cursor.fetchone()[0]
            conn.commit()

            return param_set_id

        finally:
            cursor.close()
            conn.close()

    def _get_config(self, param_set_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve configuration by ID"""
        if not param_set_id:
            return None

        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT base_order_size, base_spread_bps, update_interval_seconds,
                       update_threshold_bps, target_position, max_position_size,
                       inventory_skew_bps_per_unit, max_skew_bps,
                       inventory_skew_threshold, min_ask_buffer_bps,
                       max_spot_perp_deviation_pct, smart_order_mgmt_enabled
                FROM parameter_sets
                WHERE id = ?
            """, (param_set_id,))

            row = cursor.fetchone()
            if not row:
                return None

            return {
                'base_order_size': float(row[0]) if row[0] else None,
                'base_spread_bps': row[1],
                'update_interval_seconds': row[2],
                'update_threshold_bps': float(row[3]) if row[3] else None,
                'target_position': float(row[4]) if row[4] else None,
                'max_position_size': float(row[5]) if row[5] else None,
                'inventory_skew_bps_per_unit': float(row[6]) if row[6] else None,
                'max_skew_bps': row[7],
                'inventory_skew_threshold': float(row[8]) if row[8] else None,
                'min_ask_buffer_bps': row[9],
                'max_spot_perp_deviation_pct': float(row[10]) if row[10] else None,
                'smart_order_mgmt_enabled': row[11]
            }

        finally:
            cursor.close()
            conn.close()

    def _generate_change_summary(
        self,
        old_config: Optional[Dict],
        new_config: Dict
    ) -> str:
        """Generate human-readable summary of what changed"""
        if not old_config:
            return "Initial configuration"

        changes = []

        # Check each field for changes
        if old_config.get('base_spread_bps') != new_config.get('base_spread_bps'):
            changes.append(
                f"Spread {old_config['base_spread_bps']}→{new_config['base_spread_bps']} bps"
            )

        if old_config.get('base_order_size') != new_config.get('base_order_size'):
            changes.append(
                f"Order size {old_config['base_order_size']}→{new_config['base_order_size']}"
            )

        if old_config.get('update_interval_seconds') != new_config.get('update_interval_seconds'):
            changes.append(
                f"Update interval {old_config['update_interval_seconds']}→{new_config['update_interval_seconds']}s"
            )

        if old_config.get('smart_order_mgmt_enabled') != new_config.get('smart_order_mgmt_enabled'):
            status = "Enabled" if new_config.get('smart_order_mgmt_enabled') else "Disabled"
            changes.append(f"Smart order mgmt {status}")

        if old_config.get('update_threshold_bps') != new_config.get('update_threshold_bps'):
            changes.append(
                f"Update threshold {old_config.get('update_threshold_bps')}→{new_config.get('update_threshold_bps')} bps"
            )

        if old_config.get('max_position_size') != new_config.get('max_position_size'):
            changes.append(
                f"Max position {old_config['max_position_size']}→{new_config['max_position_size']}"
            )

        return ", ".join(changes) if changes else "Configuration updated"

    def _determine_change_type(
        self,
        old_config: Optional[Dict],
        new_config: Dict
    ) -> str:
        """Determine the type of change for categorization"""
        if not old_config:
            return "initial"

        # Prioritize by importance
        if old_config.get('smart_order_mgmt_enabled') != new_config.get('smart_order_mgmt_enabled'):
            return "smart_mgmt_toggle"

        if old_config.get('base_spread_bps') != new_config.get('base_spread_bps'):
            return "spread_adjustment"

        if old_config.get('max_position_size') != new_config.get('max_position_size'):
            return "position_limits"

        if old_config.get('base_order_size') != new_config.get('base_order_size'):
            return "order_sizing"

        if old_config.get('update_interval_seconds') != new_config.get('update_interval_seconds'):
            return "timing_adjustment"

        return "other"

    def _load_last_param_set_id(self):
        """Load the last used parameter_set_id for this pair from database"""
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Try to get the most recent parameter change for this pair
            cursor.execute("""
                SELECT new_parameter_set_id
                FROM parameter_changes
                WHERE pair = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (self.pair,))

            result = cursor.fetchone()
            if result:
                self.current_param_set_id = result[0]
                print(f"   📂 Loaded last parameter set #{self.current_param_set_id} for {self.pair}")

        finally:
            cursor.close()
            conn.close()
