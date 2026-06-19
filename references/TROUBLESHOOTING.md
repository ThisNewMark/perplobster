# Troubleshooting Guide

## Common Errors

### "Price must be divisible by tick size"
**Cause**: Wrong `price_decimals` in your config file.
**Fix**: Run `python scripts/check_market.py ASSET` — it computes the correct value.

Hyperliquid accepts a price only if it has **≤ 5 significant figures** AND
**≤ (MAX_DECIMALS − szDecimals) decimal places** (MAX_DECIMALS is 6 for perps,
8 for spot). Integer prices are always allowed. The 5-significant-figure cap is
what bites on higher-priced assets — the number of allowed decimals *shrinks* as
price grows:
- BTC (~$66,000): `price_decimals: 0` (66000 is already 5 sig figs)
- ETH (~$1,900): `price_decimals: 1` (1900.5)
- ZEC (~$453): `price_decimals: 2` (453.35 — `453.350` would be 6 sig figs and is rejected)
- HYPE (~$28): `price_decimals: 3` (28.123)
- Small altcoins (<$1): `price_decimals: 4-6`

`check_market.py` and `create_config.py` apply this rule automatically (see
`lib/price_utils.py`), so generated configs get the right value.

### "Order has zero size" / "Order value below minimum" / orders silently rejected
**Cause**: Order value is below Hyperliquid's **$10 minimum order value**.
**Fix**: This is a flat $10 (10 USDC for spot) on **every** asset — there is no
per-asset minimum. Set `base_order_size` (mm) / `order_size_usd` (grid) to at
least $10. The only exception is a reduce-only order that exactly closes a
position. `create_config.py` warns if your order size is below $10 and sets
`min_order_size` to the $10-equivalent in contracts so the bot drops sub-$10
orders locally instead of having the exchange reject them.

### "Post-only order would cross"
**Cause**: Your bid price is above the best ask, or ask is below best bid.
**Fix**: Increase `base_spread_bps` (try 30-50) or increase `update_threshold_bps`.

### "Rate limited" / "Too many cumulative requests"
**Cause**: Exceeding Hyperliquid's API rate limits (based on trading volume).
**Fix**:
- Enable `smart_order_mgmt_enabled: true` in safety config
- Increase `update_threshold_bps` to 10-15
- Place some manual taker orders to build API quota
- New accounts have very low quota until they build volume

### 422 Errors with "non-hexadecimal number found in fromhex()"
**Cause**: Wallet address is truncated or malformed.
**Fix**: Ensure all addresses are full 42-character hex strings: `0x` + 40 hex chars. Example: `0x1234567890abcdef1234567890abcdef12345678`

### "Cannot get valid anchor price"
**Cause**: The perp oracle isn't returning data.
**Fix**:
- Check `perp_coin` is the correct ticker
- Verify the perp market is active on Hyperliquid
- Try increasing `max_oracle_age_seconds` to 120

### Orders placed but not showing in Hyperliquid UI
**Cause**: Usually a subaccount configuration issue.
**Fix**:
- Verify `subaccount_address` is the correct full address
- Check you're viewing the subaccount (not main account) in HL UI
- Ensure `is_subaccount: true` is set in your config

### WebSocket disconnects / "No data received"
**Cause**: Network issues or wrong subscription format.
**Fix**: The bots auto-reconnect. If persistent:
- Check internet connection
- Verify market name format matches market type
- Check if Hyperliquid is experiencing issues (check their Discord)

### "No module named 'hyperliquid'"
**Cause**: Virtual environment not activated or dependencies not installed.
**Fix**:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Performance Tuning

### Bot not filling enough orders
- Decrease `base_spread_bps` (tighter quotes = more fills)
- Increase `base_order_size` (larger orders = more attractive)
- Decrease `update_threshold_bps` (requote more often)

### Bot accumulating too much inventory
- Increase `inventory_skew_bps_per_1k` or `inventory_skew_bps_per_unit`
- Decrease `max_position_usd` or `max_position_size`
- Set `target_position_usd` to 0 for neutral market making

### High funding rate eating profits (perp MM)
- Check `max_funding_rate_pct_8h` - lower it to pause during expensive funding
- Increase `funding_skew_multiplier` to bias away from paying funding
