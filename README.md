# Perp Lobster

Automated trading bots for [Hyperliquid](https://app.hyperliquid.xyz/join/VIBETRADE) DEX. Deploy a market maker or grid trader in under 30 minutes.

Powered by [Vibetrade.cc](https://vibetrade.cc)

## Bots Included

- **Perp Market Maker** - Make markets on perpetual futures (ETH, BTC, HYPE, etc.)
- **Spot Market Maker** - Make markets on HIP-1 spot tokens with perp oracle pricing
- **Grid Trader** - Grid trading with directional bias for range-bound assets

## Features

- Event-driven WebSocket architecture (100-300ms latency)
- JSON config files (no code changes needed)
- Smart order management (reduces API calls/fees)
- Web dashboard with AI analysis
- Subaccount support for risk isolation
- SQLite metrics tracking

## Quick Start

```bash
git clone https://github.com/ThisNewMark/perplobster.git
cd perplobster
chmod +x setup.sh
./setup.sh
```

Then edit `.env` with your Hyperliquid credentials and create a config file from the examples in `config/examples/`.

See the [full setup guide](SKILL.md) for detailed instructions.

## OpenClaw / ClawHub

This repo is also available as an [OpenClaw skill on ClawHub](https://clawhub.ai). Install it to let your AI assistant set up and manage Hyperliquid trading bots for you:

```
clawhub install perplobster
```

Or tell your OpenClaw bot: *"Set up a Hyperliquid trading bot using Perp Lobster"*

## Dashboard

```bash
python dashboards/dashboard.py
# Open http://localhost:5050
```

Features: portfolio overview, per-market stats, multi-timeframe P&L, fill quality analysis, AI-powered recommendations, config editor, and emergency stop.

## Strategy Guide

| Strategy | Best For | Risk Level |
|----------|----------|------------|
| Perp Market Making | Earning spread on liquid perps | Medium |
| Spot Market Making | HIP-1 tokens with perp oracle | Medium-High |
| Grid Trading | Range-bound assets, farming | Depends on bias |

See `references/STRATEGIES.md` for detailed strategy selection guidance.

## Referral

If you're signing up for Hyperliquid, consider using our referral link:
**https://app.hyperliquid.xyz/join/VIBETRADE**

## Disclaimer

Trading cryptocurrencies and derivatives involves substantial risk of loss. This software does not guarantee profits. Past performance is not indicative of future results. You are solely responsible for your trading decisions and any resulting gains or losses.

This software includes a builder fee of 0.01% (1 basis point) per trade to support ongoing development.

## License

MIT License - see [LICENSE](LICENSE) for details.
