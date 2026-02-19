-- Migration 002: Create metrics_1min table (SQLite)
-- Purpose: Store 1-minute time-series metrics for accurate performance tracking

-- ============================================================
-- METRICS_1MIN TABLE
-- Captures metrics at 1-minute boundaries with boundary snapshot approach
-- ============================================================

CREATE TABLE IF NOT EXISTS metrics_1min (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,  -- Exact minute boundary (e.g., '2026-01-15 14:23:00')
    pair TEXT NOT NULL,

    -- Link to active configuration at this time
    parameter_set_id INTEGER REFERENCES parameter_sets(id),

    -- Balance snapshot (point-in-time at boundary)
    base_balance REAL,      -- Available balance (not including holds)
    quote_balance REAL,     -- Available balance
    base_total REAL,        -- Total balance including holds
    quote_total REAL,       -- Total balance including holds

    -- Price data (at boundary)
    mid_price REAL,
    bid_price REAL,
    ask_price REAL,
    spread_bps REAL,

    -- Total portfolio value (calculated)
    total_value_usd REAL,   -- base_total * mid_price + quote_total

    -- Activity DURING the previous minute (timestamp-1min to timestamp)
    fills_count INTEGER DEFAULT 0,
    buy_fills INTEGER DEFAULT 0,
    sell_fills INTEGER DEFAULT 0,
    volume_base REAL DEFAULT 0,
    volume_quote REAL DEFAULT 0,

    -- PnL during previous minute (realized only - clean)
    realized_pnl REAL DEFAULT 0,
    fees_paid REAL DEFAULT 0,
    net_realized_pnl REAL DEFAULT 0,  -- realized_pnl - fees_paid

    -- Price movement during previous minute
    price_change_bps REAL,  -- Change from previous snapshot

    -- Cumulative totals (since bot start or midnight)
    cumulative_fills INTEGER DEFAULT 0,
    cumulative_volume_quote REAL DEFAULT 0,
    cumulative_realized_pnl REAL DEFAULT 0,
    cumulative_fees REAL DEFAULT 0,
    cumulative_net_pnl REAL DEFAULT 0,

    -- Bot state (at boundary)
    bot_running INTEGER DEFAULT 1,  -- SQLite uses INTEGER for boolean
    bid_live INTEGER DEFAULT 0,
    ask_live INTEGER DEFAULT 0,
    our_bid_price REAL,
    our_ask_price REAL,
    our_bid_size REAL,
    our_ask_size REAL,

    -- Spread capture analysis
    avg_spread_captured_bps REAL,  -- Average spread on fills this minute

    -- Metadata
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    -- Ensure one row per minute per pair
    UNIQUE(timestamp, pair)
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_metrics_1min_timestamp ON metrics_1min(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_1min_pair_timestamp ON metrics_1min(pair, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_1min_param_set ON metrics_1min(parameter_set_id);
CREATE INDEX IF NOT EXISTS idx_metrics_1min_pair_param_time ON metrics_1min(pair, parameter_set_id, timestamp DESC);
