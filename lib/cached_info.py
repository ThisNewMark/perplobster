"""
Cached wrapper for Hyperliquid Info API calls.

The Hyperliquid API rate-limits based on trading volume ($1 traded = 1 request).
New/low-volume accounts get rate-limited very quickly. This module caches
expensive API responses so the dashboard doesn't blow through quota.

Usage:
    from cached_info import get_info, cached_call

    info = get_info()  # shared Info instance with perp_dexs
    meta = cached_call('meta', info.meta, ttl=300)
    state = cached_call('user_state:0xABC', info.user_state, ttl=30, args=('0xABC',))
"""

import time
import threading
from hyperliquid.info import Info
from hyperliquid.utils import constants

# Known HIP-3 builder dex prefixes
KNOWN_DEXES = ["", "xyz", "flx"]

# Module-level cache: { key: (data, expiry_time) }
_cache = {}
_cache_lock = threading.Lock()

# Shared Info instance (created lazily)
_info_instance = None
_info_lock = threading.Lock()


def get_info():
    """Get a shared Info instance (created once, reused)."""
    global _info_instance
    if _info_instance is None:
        with _info_lock:
            if _info_instance is None:
                _info_instance = Info(
                    constants.MAINNET_API_URL,
                    skip_ws=True,
                    perp_dexs=KNOWN_DEXES
                )
    return _info_instance


def cached_call(key, fn, ttl=30, args=None, kwargs=None):
    """Call fn with caching. Returns cached result if within TTL.

    Args:
        key: Cache key string (e.g., 'meta', 'user_state:0xABC')
        fn: Callable to invoke on cache miss
        ttl: Time-to-live in seconds (default 30)
        args: Positional args for fn
        kwargs: Keyword args for fn

    Returns:
        The (possibly cached) result of fn(*args, **kwargs)
    """
    now = time.time()

    with _cache_lock:
        if key in _cache:
            data, expiry = _cache[key]
            if now < expiry:
                return data

    # Cache miss — call the API
    result = fn(*(args or ()), **(kwargs or {}))

    with _cache_lock:
        _cache[key] = (result, now + ttl)

    return result


def invalidate(key=None):
    """Clear cache entry or entire cache."""
    with _cache_lock:
        if key:
            _cache.pop(key, None)
        else:
            _cache.clear()


# ============================================================
# Convenience wrappers for common expensive calls
# ============================================================

def get_meta(dex="", ttl=300):
    """Get perp metadata (cached 5 minutes)."""
    info = get_info()
    return cached_call(f'meta:{dex}', info.meta, ttl=ttl, kwargs={'dex': dex})


def get_meta_and_asset_ctxs(ttl=60):
    """Get meta + asset contexts for standard markets (cached 60s)."""
    info = get_info()
    return cached_call('meta_and_asset_ctxs', info.meta_and_asset_ctxs, ttl=ttl)


def get_all_mids(dex="", ttl=15):
    """Get all mid prices (cached 15s)."""
    info = get_info()
    return cached_call(f'all_mids:{dex}', info.all_mids, ttl=ttl, kwargs={'dex': dex})


def get_user_state(address, ttl=30):
    """Get user state/positions (cached 30s)."""
    info = get_info()
    return cached_call(f'user_state:{address}', info.user_state, ttl=ttl, args=(address,))


def get_open_orders(address, dex="", ttl=15):
    """Get open orders (cached 15s)."""
    info = get_info()
    if dex:
        return cached_call(
            f'open_orders:{address}:{dex}',
            info.open_orders, ttl=ttl,
            args=(address,), kwargs={'dex': dex}
        )
    return cached_call(
        f'open_orders:{address}:',
        info.open_orders, ttl=ttl,
        args=(address,)
    )


def get_portfolio(address, ttl=120):
    """Get portfolio/account summary (cached 2 minutes — expensive call)."""
    info = get_info()
    return cached_call(
        f'portfolio:{address}',
        info.post, ttl=ttl,
        args=('/info', {'type': 'portfolio', 'user': address})
    )


def get_user_fills(address, ttl=30):
    """Get recent fills (cached 30s)."""
    info = get_info()
    return cached_call(
        f'user_fills:{address}',
        info.user_fills, ttl=ttl,
        args=(address,)
    )


def get_spot_meta(ttl=300):
    """Get spot metadata (cached 5 minutes)."""
    info = get_info()
    return cached_call('spot_meta', info.spot_meta, ttl=ttl)
