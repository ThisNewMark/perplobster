# Spot Market Making Strategy

## What It Is

Market making on spot markets by providing liquidity (bid and ask quotes) around a price oracle, earning the spread when both sides fill.

## When to Use It

- HIP-1 builder tokens that have a perp oracle (XMR1, etc.)
- Canonical spot pairs with liquid perp markets (PURR/USDC, etc.)
- When you want exposure to a token while earning trading fees

## How It Works

1. **Oracle-Based Pricing**: Uses the perp market mid price as the "true" price
2. **Spread Around Oracle**: Places bid below and ask above the oracle price
3. **Inventory Management**: Skews prices based on inventory to encourage mean reversion
4. **Event-Driven Updates**: Only updates quotes when price moves significantly

## Key Parameters

### Spread Settings

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `base_spread_bps` | Default spread width | 30-100 bps |
| `min_spread_bps` | Floor for spread | 20-50 bps |
| `max_spread_bps` | Ceiling for spread | 100-200 bps |

**Tighter spreads** = More fills, more inventory risk, lower profit per fill
**Wider spreads** = Fewer fills, less inventory risk, higher profit per fill

### Position Management

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `target_position` | Desired inventory level | 0 or small amount |
| `max_position_size` | Hard cap on inventory | Depends on capital |
| `inventory_skew_bps_per_unit` | How much to skew per unit of inventory | 5-20 bps |

### Oracle Settings

| Parameter | What It Does | Typical Range |
|-----------|--------------|---------------|
| `perp_coin` | Which perp to use as oracle | e.g., "XMR", "flx:XMR" |
| `max_oracle_age_seconds` | Stale oracle protection | 30-60s |
| `max_oracle_jump_pct` | Circuit breaker for oracle jumps | 3-5% |

## Risk Considerations

1. **Inventory Risk**: You accumulate tokens when price moves against you
2. **Oracle Risk**: If perp and spot diverge, you may quote wrong prices
3. **Illiquidity Risk**: In thin markets, you're the only liquidity provider

## Example Configuration

```json
{
  "pair": "XMR1/USDC",
  "trading": {
    "base_order_size": 0.1,
    "base_spread_bps": 50
  },
  "position": {
    "target_position": 0.5,
    "max_position_size": 1.0
  },
  "inventory": {
    "inventory_skew_bps_per_unit": 15,
    "max_skew_bps": 50
  }
}
```

## P&L Breakdown

- **Trading P&L**: Spread captured on round trips (buy low, sell high)
- **Inventory P&L**: Mark-to-market on held inventory (can be + or -)
- **Fees**: Maker rebates (you get paid) minus any taker fees

## Tips from Experience

1. Start with wider spreads and tighten based on fill rate
2. Monitor inventory closely - don't let it run away
3. Use subaccounts to isolate each market's P&L
4. Watch for spot/perp divergence in volatile markets
5. The `emergency_sell_if_below_oracle_pct` setting can save you in crashes
