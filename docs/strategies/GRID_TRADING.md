# Grid Trading Strategy

## What It Is

A fixed-level trading strategy that places orders at predetermined price levels, profiting from price oscillation within a range. Unlike market making, grid trading doesn't continuously adjust quotes - it waits for fills at specific levels.

## When to Use It

- Range-bound markets (you expect price to oscillate)
- Airdrop farming (accumulate positions over time)
- Directional bets with dollar-cost averaging
- HIP-3 builder markets (less competitive, more predictable)

## How It Works

1. **Grid Setup**: Creates price levels above and below current price
2. **Order Placement**: Places buy orders below current price, sell orders above
3. **Round Trip Profits**: When buy fills, places sell at next level up (and vice versa)
4. **Rebalancing**: If price moves far from center, grid resets around new price

## Key Parameters

### Grid Structure

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `spacing_pct` | Distance between levels | 0.3-1.0% |
| `num_levels_each_side` | How many levels up and down | 3-10 |
| `order_size_usd` | USD per order | 20-100 USD |
| `rebalance_threshold_pct` | When to reset grid | 2-5% |

### Directional Bias

| Value | Meaning | Use Case |
|-------|---------|----------|
| `"neutral"` | Equal levels both sides | Range trading |
| `"long"` | More buy levels | Accumulation, bullish |
| `"short"` | More sell levels | Distribution, bearish |

### Safety Settings

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `max_position_usd` | Maximum position size | 200-500 USD |
| `max_account_drawdown_pct` | Stop if account drops by | -15 to -25% |
| `close_position_on_emergency` | Close on emergency stop | true |

## Risk Considerations

1. **Trending Markets**: Grid loses money if price trends in one direction
2. **Position Accumulation**: Long bias + falling price = growing position
3. **Capital Efficiency**: Orders sit idle until hit
4. **Rebalance Losses**: Resetting grid may lock in losses

## Example Configuration

```json
{
  "market": "xyz:COPPER",
  "dex": "xyz",
  "grid": {
    "spacing_pct": 0.5,
    "num_levels_each_side": 5,
    "order_size_usd": 25,
    "bias": "long"
  },
  "position": {
    "max_position_usd": 300,
    "leverage": 3
  }
}
```

## Grid Visualization

For `spacing_pct: 0.5%` and `num_levels_each_side: 3` at $100:

```
$101.51  SELL level 3
$101.00  SELL level 2
$100.50  SELL level 1
$100.00  ← Current price (center)
$99.50   BUY level 1
$99.00   BUY level 2
$98.51   BUY level 3
```

## P&L Breakdown

- **Round Trip Profit**: (sell_price - buy_price) * size - fees
- **Per Grid Profit**: Approximately spacing_pct * order_size_usd
- **Inventory P&L**: Mark-to-market on accumulated position

Example: 0.5% spacing × $25 order = ~$0.125 per round trip

## Strategy Variations

### Neutral Grid (Range Trading)
- `bias: "neutral"`
- Equal levels both sides
- Best when price oscillates in a range
- Risk: loses on breakouts

### Long Bias (Accumulation)
- `bias: "long"`
- More buy levels than sell
- Accumulates position over time
- Good for: airdrop farming, DCA into a position

### Short Bias (Distribution)
- `bias: "short"`
- More sell levels than buy
- Distributes position over time
- Good for: taking profits, reducing exposure

## Tips from Experience

1. **Choose range-bound assets** - Grid profits from oscillation, not trends
2. **HIP-3 markets work well** - Less competition, more predictable movements
3. **Wider spacing = fewer trades but higher profit per trade**
4. **Long bias for airdrops** - Accumulate tokens while earning grid profits
5. **Watch position accumulation** - A falling market with long bias builds big positions
6. **Don't fight the trend** - If market is trending, pause the grid
7. **Leverage is optional** - 1x works fine if you have the capital
