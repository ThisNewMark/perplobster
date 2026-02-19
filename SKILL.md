---
name: perplobster
description: Deploy automated trading bots on Hyperliquid DEX. Supports perpetual market making, spot market making, and grid trading strategies with a web dashboard. Helps users choose a strategy, configure markets, and start trading. Use when someone wants to trade on Hyperliquid, run a market maker, set up a grid bot, or automate crypto trading.
license: MIT
homepage: https://github.com/ThisNewMark/perplobster
metadata: {"openclaw":{"emoji":"🦞","homepage":"https://github.com/ThisNewMark/perplobster","os":["darwin","linux"],"requires":{"anyBins":["python3","python"],"bins":["git"],"env":["HL_ACCOUNT_ADDRESS","HL_SECRET_KEY"]}}}
---

# Perp Lobster - Hyperliquid Trading Bots

You are helping the user deploy automated trading bots on Hyperliquid DEX using the Perp Lobster system.

Source code: https://github.com/ThisNewMark/perplobster (MIT licensed, open source)

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
python3 -c "
from hyperliquid.info import Info
from hyperliquid.utils import constants
info = Info(constants.MAINNET_API_URL, skip_ws=True)
meta = info.meta_and_asset_ctxs()
universe = meta[0]['universe']
for i, asset in enumerate(universe):
    if asset['name'].upper() == 'MARKET_NAME_HERE':
        ctx = meta[1][i]
        mark = float(ctx['markPx'])
        if mark >= 10000: decimals = 1
        elif mark >= 1000: decimals = 2
        elif mark >= 100: decimals = 3
        elif mark >= 10: decimals = 3
        elif mark >= 1: decimals = 4
        else: decimals = 5
        print(f'Asset: {asset[\"name\"]}')
        print(f'Mark price: {mark}')
        print(f'Suggested price_decimals: {decimals}')
        print(f'Size decimals: {asset.get(\"szDecimals\", 2)}')
        print(f'Max leverage: {asset.get(\"maxLeverage\", 3)}')
        break
"
```
Replace `MARKET_NAME_HERE` with the actual asset name (uppercase).

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

```bash
source venv/bin/activate

# For perp market maker:
python bots/perp_market_maker.py --config config/my_bot.json

# For spot market maker:
python bots/spot_market_maker.py --config config/my_bot.json

# For grid trader:
python bots/grid_trader.py --config config/my_bot.json
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

## Running in Background

To keep the bot running after closing the terminal:
```bash
nohup python bots/perp_market_maker.py --config config/my_bot.json > bot.log 2>&1 &
echo $! > bot.pid
```

To stop it:
```bash
kill $(cat bot.pid)
```

## Emergency Stop

If something goes wrong:
```bash
python tools/emergency_stop.py
```
This kills all bot processes and cancels all open orders.
