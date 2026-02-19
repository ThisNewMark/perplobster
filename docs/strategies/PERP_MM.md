# Perpetual Market Making Strategy

## What It Is

Market making on perpetual futures by providing liquidity around the mark price, earning the spread while managing directional exposure and funding costs.

## When to Use It

- Liquid perpetual markets (ICP, SOL, ETH, etc.)
- When you want to earn from spreads without spot token exposure
- As a delta-neutral strategy (target_position_usd = 0)

## How It Works

1. **Mark Price Quoting**: Places bid/ask around current mark price
2. **Inventory Skew**: Adjusts quotes based on position to stay neutral
3. **Funding Awareness**: Skews quotes based on funding rate direction
4. **Profit Taking**: Tightens spreads when position is profitable
5. **Leverage Management**: Uses specified leverage with margin monitoring

## Key Parameters

### Spread Settings

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `base_spread_bps` | Default spread width | 10-30 bps |
| `min_spread_bps` | Floor for spread | 5-15 bps |
| `max_spread_bps` | Ceiling for spread | 30-100 bps |

Perp markets are typically more liquid, so spreads can be tighter than spot.

### Position Management

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `target_position_usd` | Target position (0 = neutral) | 0 |
| `max_position_usd` | Maximum position size | 200-1000 USD |
| `leverage` | Leverage multiplier | 3-10x |

### Funding Settings

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `max_funding_rate_pct_8h` | Stop trading if funding exceeds | 0.3-0.5% |
| `funding_skew_multiplier` | How much to skew based on funding | 50-150 |

### Profit Taking

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `threshold_usd` | Start taking profit at this PnL | 5-20 USD |
| `aggression_bps` | How much to tighten spread | 3-10 bps |

## Risk Considerations

1. **Funding Costs**: If you hold a position, you pay/receive funding every 8h
2. **Leverage Risk**: Higher leverage = faster gains AND losses
3. **Liquidation**: Monitor margin ratio, especially in volatile markets
4. **Directional Risk**: Inventory accumulation during trends

## Example Configuration

```json
{
  "market": "ICP",
  "trading": {
    "base_order_size": 50,
    "base_spread_bps": 15
  },
  "position": {
    "target_position_usd": 0,
    "max_position_usd": 500,
    "leverage": 5
  },
  "funding": {
    "max_funding_rate_pct_8h": 0.5,
    "funding_skew_multiplier": 100
  }
}
```

## P&L Breakdown

- **Trading P&L**: Spread captured on round trips
- **Funding P&L**: Paid or received every 8 hours based on position
- **Mark-to-Market**: Unrealized PnL on current position
- **Fees**: Maker rebates (typically positive)

## Funding Rate Strategy

The bot adjusts quotes based on funding:

- **Positive funding** (longs pay shorts): Bot leans short
- **Negative funding** (shorts pay longs): Bot leans long

This helps avoid paying funding while potentially earning it.

## Tips from Experience

1. **Start with liquid markets** - ICP, SOL have good volume and tight spreads
2. **Monitor funding rates** - Don't hold positions through high funding periods
3. **Use 5x leverage or less** - Higher leverage is riskier than you think
4. **Target 0 position** - Market making profits come from spreads, not direction
5. **Watch margin ratio** - Below 20% is getting dangerous
6. **Profit taking works** - Tightening spreads when profitable closes positions faster
