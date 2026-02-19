# Perp Lobster Bot System - AI Assistant Guide

This file helps AI coding assistants (Claude Code, Cursor, etc.) understand this codebase and help users deploy trading bots quickly.

## Quick Context

This repo contains **3 production-ready automated trading bots** for Hyperliquid:

1. **Spot Market Maker** - Make markets on HIP-1 spot tokens
2. **Perp Market Maker** - Make markets on perpetual futures
3. **Grid Trader** - Fixed-level grid trading with directional bias

All bots use:
- Event-driven WebSocket architecture (100-300ms latency)
- JSON config files (no code changes needed to switch markets)
- Smart order management (reduces API calls/fees)
- SQLite metrics tracking

## Setup Flow

1. Clone repo and run `./setup.sh`
2. Edit `.env` with Hyperliquid credentials
3. Copy a config example from `config/examples/`
4. Configure for your market
5. Run the bot

## Hyperliquid Quirks (CRITICAL)

### Builder Assets Need Pair IDs
For HIP-1 builder spot markets, use `@XXX` format (e.g., `@260` for XMR1).

### Canonical Assets Use Pair Format
For core assets, use pair string (e.g., `"PURR/USDC"` for spot, `"PURR"` for perp).

### HIP-3 Builder Perps Need DEX Prefix
Use `"xyz:COPPER"` format and set `"dex": "xyz"` in config.

### Subaccounts Require Vault Address
Sign with main wallet key, set `vault_address` to subaccount address, query using subaccount address.

### Decimals Matter
Different markets need different `price_decimals` and `size_decimals`. Hyperliquid uses 5 significant figures. Get these wrong and orders will be rejected.

### Rate Limits
Based on trading volume. Every $1 traded = 1 request allowed. New accounts need to build volume.

## Key Files

- `bots/` - The three trading bots
- `lib/credentials.py` - Credential loading, builder fees, account management
- `lib/config_loader.py` - Config validation
- `lib/websocket_integration.py` - WebSocket event-driven architecture
- `config/examples/` - Example config files for each bot type
- `dashboards/dashboard.py` - Unified web dashboard (port 5050)
- `tools/init_db.py` - Database initialization
- `tools/emergency_stop.py` - Emergency stop all bots

## Builder Fees

A 1 bps (0.01%) builder fee is included on all trades to support development.
This is configured in `lib/credentials.py` via `BUILDER_ADDRESS` and `BUILDER_FEE`.

## CRITICAL RULES FOR AI ASSISTANTS

- **NEVER truncate wallet addresses.** Always use the FULL 42-character hex address (0x + 40 chars).
- **ALWAYS check correct decimals** before creating configs. Use the Hyperliquid API to verify.
- **NEVER expose or log private keys.**
- When creating configs, verify the market exists on Hyperliquid first.
