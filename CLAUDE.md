# Perp Lobster - Hyperliquid Trading

This repo contains trading tools for Hyperliquid DEX: quick perp trades via command line, plus automated bots (market making, grid trading) with a web dashboard.

## Security Rules

- **NEVER ask the user for their private key.** They must edit `.env` themselves.
- **NEVER read, cat, or display the contents of `.env`.**
- Confirm with the user before placing any trade.

## Quick Trading

When the user asks to trade, activate the venv and run the trade script. All amounts are in USD.

```bash
# Market orders
source venv/bin/activate && python scripts/trade.py long HYPE 50
source venv/bin/activate && python scripts/trade.py short ETH 100

# Limit orders
source venv/bin/activate && python scripts/trade.py long HYPE 50 --price 28.50
source venv/bin/activate && python scripts/trade.py short ETH 100 --price 1900

# Close a position
source venv/bin/activate && python scripts/trade.py close HYPE

# With leverage
source venv/bin/activate && python scripts/trade.py long HYPE 50 --leverage 3

# With subaccount
source venv/bin/activate && python scripts/trade.py long HYPE 50 --subaccount 0xAddress
```

**If you see "Builder fee has not been approved"**, run:
```bash
source venv/bin/activate && python scripts/approve_builder_fee.py
```

## Bot Management

```bash
# Start a bot (auto-detects type from config)
./start.sh config/my_bot.json

# Stop a bot
./stop.sh config/my_bot.json

# Stop all bots
./stop.sh --all

# Check what's running
./stop.sh

# View logs
tail -20 logs/my_bot.log
```

## First-Time Setup

If `.env` doesn't exist or the venv isn't set up, walk through these steps:

1. Run `cat setup.sh` and show the user what it does. After they approve, run:
   ```bash
   chmod +x setup.sh && ./setup.sh
   ```

2. Tell the user to edit `.env` with their credentials:
   ```
   nano .env

   Fill in:
     HL_ACCOUNT_ADDRESS=0xYourWalletAddress
     HL_SECRET_KEY=your_private_key_hex
   ```
   Wait for them to confirm.

3. Approve builder fee:
   ```bash
   source venv/bin/activate && python scripts/approve_builder_fee.py
   ```

4. Test with a small trade:
   ```bash
   source venv/bin/activate && python scripts/trade.py long HYPE 1
   ```

## Bot Configuration

When the user wants to run an automated bot:

1. Copy an example config:
   ```bash
   cp config/examples/perp_example.json config/my_bot.json
   ```
   Use `grid_example.json` for grid trading, `spot_example.json` for spot market making.

2. Get market decimals:
   ```bash
   source venv/bin/activate && python scripts/check_market.py HYPE
   ```

3. Edit `config/my_bot.json` with the output values:
   - `market`: Asset name (e.g., "HYPE")
   - `exchange.price_decimals`: From check_market
   - `exchange.size_decimals`: From check_market
   - `trading.base_order_size`: Start with 10-20 USD
   - `position.max_position_usd`: Start with 50-100 USD
   - `position.leverage`: 3x is safe default

   For subaccounts, add:
   ```json
   "account": {
       "subaccount_address": "0xAddress",
       "is_subaccount": true
   }
   ```

4. Start: `./start.sh config/my_bot.json`

## Dashboard

```bash
source venv/bin/activate && python dashboards/dashboard.py
```
Opens on http://localhost:5050. Optionally add `ANTHROPIC_API_KEY` to `.env` for AI analysis features.

## Market Types

- **Standard Perps**: `"ETH"`, `"BTC"`, `"HYPE"`, `"ICP"`
- **HIP-3 Builder Perps**: `"xyz:COPPER"`, `"flx:XMR"` (set `dex` in config)
- **HIP-1 Builder Spot**: `"@260"` format (needs `perp_coin` oracle)
- **Canonical Spot**: `"PURR/USDC"`

## Troubleshooting

- **"Builder fee has not been approved"**: Run `python scripts/approve_builder_fee.py`
- **"Price must be divisible by tick size"**: Run `python scripts/check_market.py ASSET` for correct decimals
- **"Post-only order would cross"**: Increase `base_spread_bps` in config
- **"Rate limited"**: Enable `smart_order_mgmt_enabled: true`, increase `update_threshold_bps`
- **422 errors with fromhex()**: Wallet addresses must be full 42 chars (0x + 40)
- **Orders not showing**: Check `subaccount_address` and `is_subaccount: true`

## Emergency Stop

```bash
source venv/bin/activate && python tools/emergency_stop.py
```

## Key Files

- `scripts/trade.py` - One-time trades (long/short/close)
- `scripts/check_market.py` - Query market decimals and info
- `scripts/approve_builder_fee.py` - One-time builder fee approval
- `bots/perp_market_maker.py` - Perp market making bot
- `bots/spot_market_maker.py` - Spot market making bot
- `bots/grid_trader.py` - Grid trading bot
- `lib/credentials.py` - Credential loading, builder fees
- `config/examples/` - Example configs for each bot type
- `dashboards/dashboard.py` - Web dashboard (port 5050)
- `tools/emergency_stop.py` - Kill all bots and cancel orders
