-- Migration 001: Create parameter_sets and parameter_changes tables (SQLite)
-- Purpose: Track bot configuration versions and changes for A/B testing

-- ============================================================
-- PARAMETER SETS TABLE
-- Stores unique bot configurations (versioned)
-- ============================================================

CREATE TABLE IF NOT EXISTS parameter_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,

    -- Identifying hash (to detect if this exact config already exists)
    config_hash TEXT NOT NULL,

    -- Core trading parameters
    base_order_size REAL NOT NULL,
    base_spread_bps INTEGER NOT NULL,
    update_interval_seconds INTEGER NOT NULL,
    update_threshold_bps REAL,  -- Threshold to trigger quote update

    -- Position management
    target_position REAL,
    max_position_size REAL NOT NULL,

    -- Inventory skew
    inventory_skew_bps_per_unit REAL,  -- e.g., 10 bps per 100 KNTQ or per 1 XMR1
    max_skew_bps INTEGER,
    inventory_skew_threshold REAL,  -- Only apply skew if delta exceeds this

    -- Safety limits (KNTQ specific)
    min_ask_buffer_bps INTEGER,  -- Minimum distance from bid to avoid post-only rejections

    -- Circuit breakers (XMR1 specific)
    max_spot_perp_deviation_pct REAL,  -- e.g., 5.0 for 5% max deviation

    -- Smart order management
    smart_order_mgmt_enabled INTEGER DEFAULT 0,  -- SQLite uses INTEGER for boolean

    -- Metadata
    description TEXT,  -- Optional user description
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'manual',  -- 'manual', 'auto', 'user_id'

    -- Ensure uniqueness per pair+config
    UNIQUE(pair, config_hash)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_parameter_sets_pair ON parameter_sets(pair);
CREATE INDEX IF NOT EXISTS idx_parameter_sets_created ON parameter_sets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_parameter_sets_pair_created ON parameter_sets(pair, created_at DESC);

-- ============================================================
-- PARAMETER CHANGES TABLE
-- Logs every configuration change for audit trail
-- ============================================================

CREATE TABLE IF NOT EXISTS parameter_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,

    -- References to old and new configurations
    old_parameter_set_id INTEGER REFERENCES parameter_sets(id),
    new_parameter_set_id INTEGER NOT NULL REFERENCES parameter_sets(id),

    -- What changed (for quick filtering and display)
    change_type TEXT,  -- 'spread_adjustment', 'position_limits', 'smart_mgmt_enabled', etc.
    change_summary TEXT,      -- Human-readable: "Spread 35→40 bps, Added smart order mgmt"

    -- Why it changed
    reason TEXT DEFAULT 'manual',  -- 'manual', 'auto_optimization', 'emergency'
    notes TEXT,          -- User notes or automatic reason details

    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for change history queries
CREATE INDEX IF NOT EXISTS idx_parameter_changes_pair_time ON parameter_changes(pair, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_parameter_changes_new_set ON parameter_changes(new_parameter_set_id);
CREATE INDEX IF NOT EXISTS idx_parameter_changes_old_set ON parameter_changes(old_parameter_set_id);
