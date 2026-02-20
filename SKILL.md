---
name: perplobster
description: Deploy automated trading bots on Hyperliquid DEX. Supports perpetual market making, spot market making, and grid trading strategies with a web dashboard. Helps users choose a strategy, configure markets, and start trading. Use when someone wants to trade on Hyperliquid, run a market maker, set up a grid bot, or automate crypto trading.
license: MIT
homepage: https://github.com/ThisNewMark/perplobster
metadata: {"openclaw":{"emoji":"🦞","homepage":"https://github.com/ThisNewMark/perplobster"}}
---

# Perp Lobster - Hyperliquid Trading Bots

You are helping the user deploy automated trading bots on Hyperliquid DEX using the Perp Lobster system.

Source code: https://github.com/ThisNewMark/perplobster (MIT licensed, open source)

## Quick Commands

If Perp Lobster is already set up (cloned + .env configured), the user can jump straight to actions:

| Command | What it does |
|---------|-------------|
| `/perplobster long 50 HYPE` | Market long $50 of HYPE perp |
| `/perplobster short 100 ETH` | Market short $100 of ETH perp |
| `/perplobster long 50 HYPE at 28.50` | Limit long at $28.50 |
| `/perplobster close HYPE` | Close entire HYPE position |
| `/perplobster start grid HYPE` | Start grid bot for HYPE |
| `/perplobster stop all` | Stop all running bots |
| `/perplobster status` | Check running bots and positions |
| `/perplobster help` | Show this command list |

### Help command

When the user asks for help (e.g., `/perplobster help` or "what can perplobster do"), respond with this message:

```
🦞 Perp Lobster Commands:

TRADING:
  long <amount> <market>            Market long (e.g., long 50 HYPE)
  short <amount> <market>           Market short (e.g., short 100 ETH)
  long <amount> <market> at <price>   Limit long (e.g., long 50 HYPE at 28.50)
  short <amount> <market> at <price>  Limit short
  close <market>                    Close position (e.g., close HYPE)

BOTS:
  start grid <market>             Start grid trading bot
  start mm <market>               Start perp market maker
  stop all                        Stop all running bots
  status                          Show running bots

SETUP:
  setup                           Full setup walkthrough
  help                            Show this message

All amounts are in USD.
```

**Parsing rules:** Extract the action, USD amount, market name, and optional price. Then run the appropriate command in the `perplobster/` directory.

### Trade commands (long/short/close)

Run from the perplobster directory:
```bash
cd perplobster && source venv/bin/activate

# Market orders
python scripts/trade.py long HYPE 50
python scripts/trade.py short ETH 100

# Limit orders
python scripts/trade.py long HYPE 50 --price 28.50
python scripts/trade.py short ETH 100 --price 1900

# Close a position
python scripts/trade.py close HYPE

# With subaccount
python scripts/trade.py long HYPE 50 --subaccount 0xSubaccountAddress

# Set leverage
python scripts/trade.py long HYPE 50 --leverage 5
```

### Bot commands (start/stop/status)
```bash
cd perplobster

# Start a bot
./start.sh config/my_bot.json

# Stop a bot
./stop.sh config/my_bot.json

# Stop all bots
./stop.sh --all

# Check what's running
./stop.sh
```

## IMPORTANT SAFETY WARNINGS

Before doing ANYTHING, tell the user:
1. **Trading is risky.** They can lose all their funds. This is not financial advice.
2. **Use a subaccount** with limited funds. Never put all funds in a bot.
3. **Start small.** Use minimum order sizes until comfortable.
4. **Monitor actively** until they understand bot behavior.

## SECURITY RULES

- **NEVER ask the user to paste their private key in chat.** Private keys must only be entered by the user directly into the `.env` file using a text editor. Tell them: "Open the .env file in a text editor and paste your credentials there. Do NOT share your private key in this chat."
- **NEVER log, echo, or display the contents of `.env`** or any file containing credentials.
- The `.env` file stays local on the user's machine and is excluded from git via `.gitignore`.
- Recommend the user **inspect the repository** before running setup: `cat setup.sh` to review what it does.
- The optional `ANTHROPIC_API_KEY` env var is used only for the AI dashboard analysis feature and is sent to Anthropic's API. Users should treat it as sensitive.

## Setup Flow

### Step 1: Clone and Install

Clone the open-source repository and review the setup script before running:

```bash
git clone https://github.com/ThisNewMark/perplobster.git
cd perplobster
```

Tell the user: **"Before running setup, you can inspect the script with `cat setup.sh` to see exactly what it does. It creates a Python virtual environment, installs pip dependencies, and initializes a local SQLite database. No data is sent externally."**

Then run:
```bash
chmod +x setup.sh
./setup.sh
```

### Step 2: Configure Credentials

**IMPORTANT: Do NOT ask the user for their private key in this conversation.**

Tell the user to edit the `.env` file directly in a text editor:

```
Open the .env file that was created during setup and fill in your Hyperliquid credentials:

  HL_ACCOUNT_ADDRESS=0xYourWalletAddress
  HL_SECRET_KEY=your_private_key_hex

You can use nano, vim, or any text editor:
  nano .env

The private key is a 64-character hex string without the 0x prefix.
Your credentials stay local in this file and are never transmitted by the bot.
```

If the user wants AI analysis features on the dashboard, they can optionally add their Anthropic API key to the same `.env` file.

### Step 3: Choose a Strategy

Ask the user what they want to do. Match to one of these:

| Strategy | Best For | Bot File | Example Config |
|----------|----------|----------|---------------|
| **Perp Market Making** | Earning spread on perpetual futures | `bots/perp_market_maker.py` | `config/examples/perp_example.json` |
| **Spot Market Making** | Making markets on HIP-1 spot tokens | `bots/spot_market_maker.py` | `config/examples/spot_example.json` |
| **Grid Trading** | Range-bound assets, farming, directional bets | `bots/grid_trader.py` | `config/examples/grid_example.json` |

**If unsure, recommend Perp Market Making** - it's the simplest to set up and most liquid.

### Step 4: Configure the Market

1. Copy the appropriate example config:
```bash
cp config/examples/perp_example.json config/my_bot.json
```

2. Ask the user which market/asset they want to trade (e.g., "ETH", "BTC", "HYPE", "ICP").

3. **Get correct decimals**: Query the Hyperliquid API to find the right tick size:
```bash
source venv/bin/activate
python scripts/check_market.py HYPE
```
Replace `HYPE` with the actual asset name (e.g., ETH, BTC, ICP).

4. Edit the config JSON with the correct values. Key fields:
   - `market`: The asset name (e.g., "ETH", "HYPE")
   - `exchange.price_decimals`: From the query above
   - `exchange.size_decimals`: From the query above
   - `trading.base_order_size`: Start with 10-20 USD
   - `position.max_position_usd`: Their max exposure (start 50-100 USD)
   - `position.leverage`: 3x is a safe default

**For subaccounts** (recommended), add:
```json
"account": {
    "subaccount_address": "0xTheirSubaccountAddress",
    "is_subaccount": true
}
```

### Step 5: Start the Bot

Use the start script to run the bot in the background with logging:

```bash
./start.sh config/my_bot.json
```

The start script auto-detects the bot type from your config (grid, perp MM, or spot MM), starts it in the background, and saves logs to `logs/`.

On first run, the bot will automatically approve a small builder fee (0.01% per trade) that supports Perp Lobster development. This is a one-time on-chain approval using the wallet in your `.env`.

**View logs:**
```bash
tail -f logs/my_bot.log
```

**Stop the bot:**
```bash
./stop.sh config/my_bot.json
# Or stop all bots:
./stop.sh --all
```

### Step 6: Start the Dashboard (Optional)

In a separate terminal:
```bash
cd perplobster
source venv/bin/activate
python dashboards/dashboard.py
```
Then open http://localhost:5050 in a browser.

## Hyperliquid Market Types

### Standard Perps
- Market name is just the ticker: `"ETH"`, `"BTC"`, `"HYPE"`, `"ICP"`
- `dex` field should be empty string `""`

### HIP-3 Builder Perps
- Market name includes dex prefix: `"xyz:COPPER"`, `"flx:XMR"`
- Set `dex` field to the prefix: `"xyz"` or `"flx"`

### HIP-1 Builder Spot
- Use `@` index format: `"@260"` for XMR1, `"@404"` for other builder tokens
- Need a perp oracle (set `perp_coin` in config)

### Canonical Spot
- Use pair format: `"PURR/USDC"`

## Troubleshooting

If you encounter errors, check `references/TROUBLESHOOTING.md` in the skill directory for common issues. Key ones:

- **"Price must be divisible by tick size"**: Wrong `price_decimals` in config. Re-run the decimal query above.
- **"Post-only order would cross"**: Spread is too tight. Increase `base_spread_bps`.
- **"Rate limited"**: Too many API calls. Enable `smart_order_mgmt_enabled: true` and increase `update_threshold_bps`.
- **422 errors with fromhex()**: Check that wallet addresses are full 42-character hex strings (0x + 40 chars). NEVER truncate addresses.
- **Orders not showing**: If using subaccounts, verify `subaccount_address` is correct and `is_subaccount` is true.

## Emergency Stop

If something goes wrong:
```bash
python tools/emergency_stop.py
```
This kills all bot processes and cancels all open orders.
