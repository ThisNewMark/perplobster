-- Migration 003: Create fills table
-- Purpose: Track all trade fills for PnL calculation and analysis

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Trade identification
    pair TEXT NOT NULL,
    timestamp TEXT NOT NULL,

    -- Fill details
    side TEXT NOT NULL,  -- 'buy' or 'sell'
    price REAL NOT NULL,
    base_amount REAL NOT NULL,  -- Amount of base asset (KNTQ, XMR1)
    quote_amount REAL NOT NULL,  -- Amount of quote asset (USDH, USDC)

    -- Costs and PnL
    fee REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    spread_bps REAL,  -- Spread captured on this fill

    -- Order context
    order_id TEXT,  -- Hyperliquid order ID
    is_maker INTEGER DEFAULT 1,  -- 1 if maker, 0 if taker

    -- Metadata
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    -- Prevent duplicates
    UNIQUE(pair, timestamp, order_id)
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_fills_pair_timestamp ON fills(pair, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fills_timestamp ON fills(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fills_pair_side ON fills(pair, side);
