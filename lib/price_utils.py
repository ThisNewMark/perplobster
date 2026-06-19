"""
Price/decimal helpers for Hyperliquid order formatting.

Hyperliquid's price validity rule (the source of "Price must be divisible by
tick size" rejections):

  A price is valid if it has
    - at most 5 significant figures, AND
    - at most (MAX_DECIMALS - szDecimals) decimal places,
  where MAX_DECIMALS is 6 for perps and 8 for spot.
  Integer prices are always allowed, regardless of significant figures.

The 5-significant-figure cap is the part that bites on higher-priced assets:
e.g. ZEC at ~$453 only allows 2 decimals (453.35), not 3 (453.350 = 6 sig figs).
"""

import math


def valid_price_decimals(price: float, sz_decimals: int, is_spot: bool = False) -> int:
    """Return the maximum number of price decimal places Hyperliquid will accept.

    Args:
        price: Current mark/mid price of the asset.
        sz_decimals: The asset's szDecimals (size decimals) from the meta.
        is_spot: True for spot markets (MAX_DECIMALS=8), False for perps (=6).

    Returns:
        A non-negative int suitable for rounding prices / setting
        exchange.price_decimals in a config.
    """
    if price <= 0:
        return 0

    max_decimals = 8 if is_spot else 6

    # 5-significant-figure cap.
    if price >= 1:
        int_digits = int(math.floor(math.log10(price))) + 1
        sig_fig_decimals = max(0, 5 - int_digits)
    else:
        # Leading zeros after the decimal point are not significant,
        # so sub-$1 prices get extra decimals (e.g. 0.012345 -> 6 dp).
        leading_zeros = -int(math.floor(math.log10(price))) - 1
        sig_fig_decimals = leading_zeros + 5

    # Also bounded by MAX_DECIMALS - szDecimals.
    return max(0, min(sig_fig_decimals, max_decimals - sz_decimals))


# Hyperliquid enforces a $10 minimum order value on all assets (10 USDC for
# spot). The only exception is a reduce-only order that exactly closes a
# position. There is no per-asset minimum — it's a flat global rule.
MIN_ORDER_NOTIONAL_USD = 10.0


def min_order_size(price: float, sz_decimals: int,
                   min_notional: float = MIN_ORDER_NOTIONAL_USD) -> float:
    """Smallest order size (in contracts/units) that meets the $10 minimum.

    Rounds UP to the asset's szDecimals, since rounding down could land the
    order just under the $10 floor and get it rejected.

    Args:
        price: Current mark/mid price of the asset.
        sz_decimals: The asset's szDecimals.
        min_notional: Minimum order value in USD (default $10).

    Returns:
        The minimum valid order size, as a float rounded to sz_decimals.
    """
    step = 10 ** -sz_decimals
    if price <= 0:
        return step
    raw_units = min_notional / price
    # Round the number of size-steps up so notional >= min_notional.
    n_steps = math.ceil(raw_units / step)
    return round(n_steps * step, sz_decimals)

