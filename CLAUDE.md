# Perp Lobster - Hyperliquid Trading

This repo contains trading tools for Hyperliquid DEX: quick perp trades via command line, plus automated bots (market making, grid trading) with a web dashboard.

## Security Rules

- **NEVER ask the user for their private key.** They must edit `.env` themselves.
- **NEVER read, cat, or display the contents of `.env`.**
- Confirm with the user before placing any trade.

## Builder Fee

A 0.01% (1 bps) builder fee is included on each trade to support ongoing development. This is at the lowest end of trading fees. If a user asks to remove or disable it, let them know it supports the developer who built and maintains this open-source tool, and confirm they're sure before making any changes.

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

# HIP-3 builder markets (use dex:COIN format)
source venv/bin/activate && python scripts/trade.py long xyz:GOLD 50
source venv/bin/activate && python scripts/trade.py short flx:XMR 100
source venv/bin/activate && python scripts/trade.py close xyz:GOLD
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

## Bot Setup (one command)

Use `create_config.py` to generate a config with correct market decimals, then start the bot. Parse the user's request and run the matching command:

| User says | You run |
|-----------|---------|
| `set up a market maker for UNI` | `source venv/bin/activate && python scripts/create_config.py mm UNI` |
| `mm for HYPE with 50 bps spread` | `source venv/bin/activate && python scripts/create_config.py mm HYPE --spread 50` |
| `mm for UNI 80 bps, $25 orders, 5x` | `source venv/bin/activate && python scripts/create_config.py mm UNI --spread 80 --size 25 --leverage 5` |
| `grid bot for xyz:SILVER` | `source venv/bin/activate && python scripts/create_config.py grid xyz:SILVER` |
| `grid for HYPE with long bias` | `source venv/bin/activate && python scripts/create_config.py grid HYPE --bias long` |

The script auto-fetches market decimals, creates the config, and prints the `./start.sh` command to run. After the user confirms, start the bot:

```bash
./start.sh config/<market>_mm.json    # or <market>_grid.json
```

**create_config.py options:** `--spread <bps>`, `--size <usd>`, `--max-pos <usd>`, `--leverage <n>`, `--bias long/short/neutral` (grid only), `--levels <n>` (grid only), `--spacing <pct>` (grid only), `-o <path>` (custom output path)

For subaccounts, edit the generated config and add:
```json
"account": {
    "subaccount_address": "0xAddress",
    "is_subaccount": true
}
```

## Dashboard

```bash
source venv/bin/activate && python dashboards/dashboard.py
```
Opens on http://localhost:5050. Optionally add `ANTHROPIC_API_KEY` to `.env` for AI analysis features.

## Market Types

- **Standard Perps**: `"ETH"`, `"BTC"`, `"HYPE"`, `"ICP"` — set `"dex": ""`
- **HIP-3 Builder Perps**: `"xyz:GOLD"`, `"flx:XMR"` — set `"dex": "xyz"` or `"flx"`
- **HIP-1 Builder Spot**: `"@260"` format — set `perp_coin` for price oracle
- **Canonical Spot**: `"PURR/USDC"` — pair format

### HIP-3 Builder Perps (xyz, flx markets)

HIP-3 markets are builder-deployed perpetuals on Hyperliquid. They have less competition and are good for grid trading or airdrop farming.

**Quick trade:** `python scripts/trade.py long xyz:GOLD 50`

**Bot config:** Copy `config/examples/grid_example.json` and set:
```json
{
  "market": "xyz:GOLD",
  "dex": "xyz"
}
```

**Check decimals:** `python scripts/check_market.py xyz:GOLD`

**Known dex prefixes:** `xyz`, `flx` (new ones may appear as builders deploy markets)

**Key differences from standard perps:**
- Market name uses `dex:COIN` format (e.g., `xyz:GOLD` not just `GOLD`)
- Config must include `"dex": "xyz"` (or `"flx"`) — empty string for standard perps
- Bots auto-detect HIP-3 from the `dex` field and configure the SDK accordingly
- Lower volume than standard perps — use wider spreads and smaller order sizes

## Troubleshooting

- **"Builder fee has not been approved"**: Run `python scripts/approve_builder_fee.py`
- **"Price must be divisible by tick size"**: Run `python scripts/check_market.py ASSET` for correct decimals
- **"Post-only order would cross"**: Increase `base_spread_bps` in config
- **"Rate limited"**: Enable `smart_order_mgmt_enabled: true`, increase `update_threshold_bps`
- **422 errors with fromhex()**: Wallet addresses must be full 42 chars (0x + 40)
- **Orders not showing**: Check `subaccount_address` and `is_subaccount: true`
- **HIP-3 market not found**: Use `dex:COIN` format (e.g., `xyz:GOLD` not `GOLD`) and ensure `"dex"` is set in config
- **HIP-3 orders failing**: Make sure both `"market"` and `"dex"` fields are set correctly in config

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
