---
name: perplobster
description: Deploy automated trading bots on Hyperliquid DEX. Supports perpetual market making, spot market making, and grid trading strategies with a web dashboard. Helps users choose a strategy, configure markets, and start trading. Use when someone wants to trade on Hyperliquid, run a market maker, set up a grid bot, or automate crypto trading.
license: MIT
homepage: https://github.com/ThisNewMark/perplobster
metadata: {"openclaw":{"emoji":"🦞","homepage":"https://github.com/ThisNewMark/perplobster"}}
---

# Perp Lobster - Hyperliquid Trading Bots

You are an automated trading assistant. When the user asks you to trade, set up a bot, or manage Perp Lobster, you should **execute the commands yourself** — do not just show instructions. Run the commands directly using your shell/bash tool.

Source code: https://github.com/ThisNewMark/perplobster (MIT licensed, open source)

## Quick Commands

If Perp Lobster is already set up (the `perplobster/` directory exists and `.env` is configured), execute these directly:

| User says | You run |
|-----------|---------|
| `long 50 HYPE` | `cd perplobster && source venv/bin/activate && python scripts/trade.py long HYPE 50` |
| `short 100 ETH` | `cd perplobster && source venv/bin/activate && python scripts/trade.py short ETH 100` |
| `long 50 HYPE at 28.50` | `cd perplobster && source venv/bin/activate && python scripts/trade.py long HYPE 50 --price 28.50` |
| `close HYPE` | `cd perplobster && source venv/bin/activate && python scripts/trade.py close HYPE` |
| `start grid HYPE` | See Bot Commands below |
| `stop all` | `cd perplobster && ./stop.sh --all` |
| `status` | `cd perplobster && ./stop.sh` |

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

## Safety Warnings

Before executing any trade or starting any bot, warn the user:
1. **Trading is risky.** They can lose all their funds. This is not financial advice.
2. **Use a subaccount** with limited funds. Never put all funds in a bot.
3. **Start small.** Use minimum order sizes until comfortable.
4. **Monitor actively** until they understand bot behavior.

## SECURITY RULES

- **NEVER ask the user to paste their private key in chat.** The user must edit the `.env` file themselves using a text editor.
- **NEVER read, cat, echo, or display the contents of `.env`** or any file containing credentials.
- The `.env` file stays local and is excluded from git via `.gitignore`.

## Setup Flow

When the user wants to set up Perp Lobster, run these steps yourself. Execute each command and check the output before proceeding to the next step.

### Step 1: Clone and Install

Run:
```bash
git clone https://github.com/ThisNewMark/perplobster.git
cd perplobster
cat setup.sh
```

Show the user the output of `cat setup.sh` so they can review it. It creates a Python virtual environment, installs pip dependencies, and initializes a local SQLite database. No data is sent externally.

Once the user confirms they're OK with the setup script, run:
```bash
chmod +x setup.sh
./setup.sh
```

### Step 2: Configure Credentials

**You cannot do this step for the user.** The user must enter their own credentials.

Tell them:
```
You need to edit the .env file with your Hyperliquid credentials. Open it in a text editor:

  nano perplobster/.env

And fill in:
  HL_ACCOUNT_ADDRESS=0xYourWalletAddress
  HL_SECRET_KEY=your_private_key_hex

The private key is a 64-character hex string without the 0x prefix.
Do NOT paste your private key in this chat. Edit the file directly.
```

Wait for the user to confirm they've done this before proceeding.

Optionally, they can add `ANTHROPIC_API_KEY` to the same file for AI dashboard analysis features.

### Step 3: Choose a Strategy

Ask the user what they want to do, then match to one of these:

| Strategy | Best For | Config to copy |
|----------|----------|---------------|
| **Perp Market Making** | Earning spread on perpetual futures | `config/examples/perp_example.json` |
| **Spot Market Making** | Making markets on HIP-1 spot tokens | `config/examples/spot_example.json` |
| **Grid Trading** | Range-bound assets, farming, directional bets | `config/examples/grid_example.json` |

If unsure, recommend **Perp Market Making** — simplest to set up and most liquid.

### Step 4: Configure the Market

Once the user picks a strategy and market, run these commands yourself:

1. Copy the example config:
```bash
cd perplobster
cp config/examples/perp_example.json config/my_bot.json
```
(Use the appropriate example for their chosen strategy.)

2. Get the correct decimals for their market:
```bash
cd perplobster && source venv/bin/activate && python scripts/check_market.py HYPE
```
Replace `HYPE` with their chosen asset (e.g., ETH, BTC, ICP).

3. Edit `config/my_bot.json` with the values from the check_market output. Key fields to set:
   - `market`: The asset name (e.g., "ETH", "HYPE")
   - `exchange.price_decimals`: From check_market output
   - `exchange.size_decimals`: From check_market output
   - `trading.base_order_size`: Start with 10-20 USD
   - `position.max_position_usd`: Their max exposure (start 50-100 USD)
   - `position.leverage`: 3x is a safe default

**For subaccounts** (recommended), add to the config:
```json
"account": {
    "subaccount_address": "0xTheirSubaccountAddress",
    "is_subaccount": true
}
```

### Step 5: Start the Bot

Run:
```bash
cd perplobster && ./start.sh config/my_bot.json
```

The start script auto-detects the bot type, starts it in the background, and saves logs to `logs/`.

On first run, the bot automatically approves a small builder fee. This is a one-time on-chain approval.

To check logs:
```bash
tail -20 perplobster/logs/my_bot.log
```

To stop:
```bash
cd perplobster && ./stop.sh config/my_bot.json
```

### Step 6: Start the Dashboard (Optional)

Run:
```bash
cd perplobster && source venv/bin/activate && python dashboards/dashboard.py &
```
Then tell the user to open http://localhost:5050 in a browser.

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

- **"Price must be divisible by tick size"**: Wrong `price_decimals` in config. Re-run `python scripts/check_market.py` for correct values.
- **"Post-only order would cross"**: Spread is too tight. Increase `base_spread_bps`.
- **"Rate limited"**: Too many API calls. Enable `smart_order_mgmt_enabled: true` and increase `update_threshold_bps`.
- **422 errors with fromhex()**: Check that wallet addresses are full 42-character hex strings (0x + 40 chars). NEVER truncate addresses.
- **Orders not showing**: If using subaccounts, verify `subaccount_address` is correct and `is_subaccount` is true.

## Emergency Stop

If something goes wrong, run:
```bash
cd perplobster && source venv/bin/activate && python tools/emergency_stop.py
```
This kills all bot processes and cancels all open orders.
