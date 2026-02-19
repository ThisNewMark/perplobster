#!/usr/bin/env python3
"""
AI Assistant Blueprint
Provides Claude-powered config creation and strategy analysis
Includes slide-out chat panel that can be embedded in any page
"""

from flask import Blueprint, render_template_string, jsonify, request
import anthropic
import json
import os
import sys
import sqlite3
from datetime import datetime, timedelta

# Create blueprint
ai_bp = Blueprint('ai_assistant', __name__, url_prefix='/ai')

# Paths
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.ai_settings.json')
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'trading_data.db')

# Add lib to path for credentials
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lib'))

# Pending actions (proposed but not yet confirmed)
pending_actions = {}


def load_settings():
    """Load AI settings from .env (falls back to .ai_settings.json)"""
    from credentials import get_ai_settings
    return get_ai_settings()


def save_settings(settings):
    """Save AI settings to file (for UI-edited values)"""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


# ============================================================================
# TOOLS FOR CLAUDE
# ============================================================================

def get_market_info(symbol: str) -> dict:
    """Look up market info from Hyperliquid API"""
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        meta = info.meta()

        # Search in perp markets
        for market in meta.get('universe', []):
            if market['name'].upper() == symbol.upper():
                return {
                    'found': True,
                    'type': 'perp',
                    'symbol': market['name'],
                    'size_decimals': market.get('szDecimals', 2),
                    'max_leverage': market.get('maxLeverage', 50),
                    'raw': market
                }

        # Search in spot markets
        spot_meta = info.spot_meta()
        for i, market in enumerate(spot_meta.get('tokens', [])):
            if market.get('name', '').upper() == symbol.upper():
                return {
                    'found': True,
                    'type': 'spot',
                    'symbol': market['name'],
                    'token_id': market.get('tokenId'),
                    'size_decimals': market.get('szDecimals', 2),
                    'wei_decimals': market.get('weiDecimals', 8),
                    'raw': market
                }

        # Check spot universe for pairs
        for market in spot_meta.get('universe', []):
            tokens = market.get('tokens', [])
            if len(tokens) >= 2:
                name = market.get('name', '')
                if symbol.upper() in name.upper():
                    return {
                        'found': True,
                        'type': 'spot_pair',
                        'name': name,
                        'index': market.get('index'),
                        'tokens': tokens,
                        'raw': market
                    }

        return {'found': False, 'error': f'Market {symbol} not found'}

    except Exception as e:
        return {'found': False, 'error': str(e)}


def get_spot_coin_id(symbol: str) -> dict:
    """Get the spot coin identifier for Hyperliquid"""
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        spot_meta = info.spot_meta()

        results = []

        for token in spot_meta.get('tokens', []):
            if symbol.upper() in token.get('name', '').upper():
                results.append({
                    'name': token.get('name'),
                    'token_id': token.get('tokenId'),
                    'index': token.get('index'),
                    'is_canonical': token.get('isCanonical', False),
                    'spot_coin_format': f"@{token.get('index')}" if not token.get('isCanonical') else f"{token.get('name')}/USDC"
                })

        for market in spot_meta.get('universe', []):
            name = market.get('name', '')
            if symbol.upper() in name.upper():
                idx = market.get('index')
                results.append({
                    'pair_name': name,
                    'index': idx,
                    'spot_coin_format': f"@{idx}" if idx else name
                })

        if results:
            return {'found': True, 'results': results}
        return {'found': False, 'error': f'No spot market found for {symbol}'}

    except Exception as e:
        return {'found': False, 'error': str(e)}


def read_config(filename: str) -> dict:
    """Read a config file"""
    try:
        filepath = os.path.join(CONFIG_DIR, filename)
        if not os.path.exists(filepath):
            return {'found': False, 'error': f'Config {filename} not found'}

        with open(filepath, 'r') as f:
            config = json.load(f)

        return {'found': True, 'config': config, 'filepath': filepath}
    except Exception as e:
        return {'found': False, 'error': str(e)}


def list_configs() -> dict:
    """List all config files"""
    try:
        configs = []
        for filename in os.listdir(CONFIG_DIR):
            if filename.endswith('.json') and filename != 'config.json':
                filepath = os.path.join(CONFIG_DIR, filename)
                with open(filepath, 'r') as f:
                    config = json.load(f)

                if 'pair' in config:
                    config_type = 'spot'
                    market = config.get('pair')
                elif 'grid' in config:
                    config_type = 'grid'
                    market = config.get('market')
                elif 'market' in config:
                    config_type = 'perp'
                    market = config.get('market')
                else:
                    config_type = 'unknown'
                    market = 'unknown'

                configs.append({
                    'filename': filename,
                    'type': config_type,
                    'market': market,
                    'description': config.get('description', '')
                })

        return {'configs': configs}
    except Exception as e:
        return {'error': str(e)}


def get_performance_metrics(config_filename: str, window: str = '24h') -> dict:
    """Get trading performance metrics for a config"""
    try:
        config_result = read_config(config_filename)
        if not config_result.get('found'):
            return {'error': f'Config not found: {config_filename}'}

        config = config_result['config']

        if 'pair' in config:
            market = config['pair']
        elif 'grid' in config:
            market = f"{config.get('market')}-PERP"
        else:
            market = f"{config.get('market')}-PERP"

        now = datetime.utcnow()
        if window == '1h':
            start_time = now - timedelta(hours=1)
        elif window == '4h':
            start_time = now - timedelta(hours=4)
        elif window == '8h':
            start_time = now - timedelta(hours=8)
        elif window == '24h':
            start_time = now - timedelta(hours=24)
        elif window == '7d':
            start_time = now - timedelta(days=7)
        else:
            start_time = now - timedelta(hours=24)

        start_str = start_time.strftime('%Y-%m-%d %H:%M:%S')

        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_fills,
                SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buys,
                SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sells,
                SUM(quote_amount) as volume,
                SUM(fee) as total_fees,
                SUM(realized_pnl) as realized_pnl,
                AVG(spread_bps) as avg_spread_captured
            FROM fills
            WHERE pair = ? AND timestamp >= ?
        """, (market, start_str))

        fills_row = cursor.fetchone()

        cursor.execute("""
            SELECT
                COUNT(*) as minutes,
                SUM(CASE WHEN bid_live = 1 AND ask_live = 1 THEN 1 ELSE 0 END) as both_live_minutes
            FROM metrics_1min
            WHERE pair = ? AND timestamp >= ?
        """, (market, start_str))

        metrics_row = cursor.fetchone()
        conn.close()

        total_fills = fills_row['total_fills'] or 0
        hours = (now - start_time).total_seconds() / 3600
        fills_per_hour = total_fills / hours if hours > 0 else 0

        uptime_pct = None
        if metrics_row and metrics_row['minutes'] and metrics_row['minutes'] > 0:
            uptime_pct = (metrics_row['both_live_minutes'] or 0) / metrics_row['minutes'] * 100

        return {
            'market': market,
            'window': window,
            'total_fills': total_fills,
            'buys': fills_row['buys'] or 0,
            'sells': fills_row['sells'] or 0,
            'volume_usd': round(fills_row['volume'] or 0, 2),
            'total_fees': round(fills_row['total_fees'] or 0, 4),
            'realized_pnl': round(fills_row['realized_pnl'] or 0, 4),
            'avg_spread_captured_bps': round(fills_row['avg_spread_captured'] or 0, 2) if fills_row['avg_spread_captured'] else None,
            'fills_per_hour': round(fills_per_hour, 2),
            'uptime_pct': round(uptime_pct, 1) if uptime_pct else None,
            'hours': round(hours, 1)
        }

    except Exception as e:
        return {'error': str(e)}


def _get_hl_info():
    """Create a Hyperliquid Info client with HIP-3 support"""
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    return Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=["", "xyz", "flx"])


def _get_all_addresses() -> list:
    """Get main account + all subaccount addresses from accounts.json"""
    from credentials import get_all_addresses
    return get_all_addresses()


def get_account_balances(address: str = None) -> dict:
    """Get account balances (USDC + spot tokens + perp margin summary)"""
    try:
        info = _get_hl_info()

        if address:
            accounts = [{'address': address, 'label': 'Requested'}]
        else:
            accounts = _get_all_addresses()

        results = []
        for acct in accounts:
            addr = acct['address']
            if not addr:
                continue

            # Perp account state (margin, account value)
            user_state = info.user_state(addr)
            margin = user_state.get('marginSummary', {})

            # Spot balances
            spot_resp = info.post("/info", {"type": "spotClearinghouseState", "user": addr})
            spot_balances = spot_resp.get('balances', []) if isinstance(spot_resp, dict) else []

            results.append({
                'label': acct['label'],
                'address': addr[:10] + '...' + addr[-4:],
                'account_value_usd': margin.get('accountValue'),
                'total_margin_used': margin.get('totalMarginUsed'),
                'withdrawable': margin.get('withdrawable'),
                'total_notional_position': margin.get('totalNtlPos'),
                'spot_balances': [
                    {'coin': b['coin'], 'total': b['total'], 'hold': b['hold']}
                    for b in spot_balances if float(b.get('total', 0)) != 0
                ]
            })

        return {'accounts': results}

    except Exception as e:
        return {'error': str(e)}


def get_open_positions(address: str = None) -> dict:
    """Get current open perp positions with PnL"""
    try:
        info = _get_hl_info()

        if address:
            accounts = [{'address': address, 'label': 'Requested'}]
        else:
            accounts = _get_all_addresses()

        results = []
        for acct in accounts:
            addr = acct['address']
            if not addr:
                continue

            user_state = info.user_state(addr)
            positions = []
            for pos in user_state.get('assetPositions', []):
                p = pos.get('position', {})
                if float(p.get('szi', 0)) != 0:
                    positions.append({
                        'coin': p.get('coin'),
                        'size': p.get('szi'),
                        'entry_price': p.get('entryPx'),
                        'mark_price': p.get('positionValue') and str(round(abs(float(p.get('positionValue', 0))) / max(abs(float(p.get('szi', 1))), 0.0001), 4)),
                        'unrealized_pnl': p.get('unrealizedPnl'),
                        'return_on_equity': p.get('returnOnEquity'),
                        'leverage_type': p.get('leverage', {}).get('type'),
                        'leverage_value': p.get('leverage', {}).get('value'),
                        'liquidation_price': p.get('liquidationPx'),
                        'margin_used': p.get('marginUsed')
                    })

            if positions:
                results.append({
                    'label': acct['label'],
                    'address': addr[:10] + '...' + addr[-4:],
                    'positions': positions
                })

        return {'accounts_with_positions': results} if results else {'message': 'No open positions found'}

    except Exception as e:
        return {'error': str(e)}


def get_open_orders(address: str = None) -> dict:
    """Get current open orders"""
    try:
        info = _get_hl_info()

        if address:
            accounts = [{'address': address, 'label': 'Requested'}]
        else:
            accounts = _get_all_addresses()

        results = []
        dexes = ["", "xyz", "flx"]

        for acct in accounts:
            addr = acct['address']
            if not addr:
                continue

            orders = []
            for dex in dexes:
                try:
                    if dex:
                        dex_orders = info.open_orders(addr, dex=dex)
                    else:
                        dex_orders = info.open_orders(addr)
                    for o in dex_orders:
                        orders.append({
                            'coin': o.get('coin'),
                            'side': 'Buy' if o.get('side') == 'B' else 'Sell',
                            'price': o.get('limitPx'),
                            'size': o.get('sz'),
                            'order_id': o.get('oid'),
                            'dex': dex or 'main'
                        })
                except:
                    pass

            if orders:
                results.append({
                    'label': acct['label'],
                    'address': addr[:10] + '...' + addr[-4:],
                    'order_count': len(orders),
                    'orders': orders
                })

        return {'accounts_with_orders': results} if results else {'message': 'No open orders found'}

    except Exception as e:
        return {'error': str(e)}


def get_current_prices(symbols: list = None) -> dict:
    """Get current mark prices for markets"""
    try:
        info = _get_hl_info()
        all_mids = info.all_mids()

        if symbols:
            filtered = {}
            for sym in symbols:
                sym_upper = sym.upper()
                for k, v in all_mids.items():
                    if sym_upper in k.upper():
                        filtered[k] = v
            return {'prices': filtered} if filtered else {'error': f'No prices found for {symbols}'}

        # If no filter, return a manageable subset (markets we trade)
        our_markets = set()
        for filename in os.listdir(CONFIG_DIR):
            if not filename.endswith('.json') or filename == 'config.json':
                continue
            try:
                with open(os.path.join(CONFIG_DIR, filename), 'r') as f:
                    cfg = json.load(f)
                if 'market' in cfg:
                    our_markets.add(cfg['market'].upper())
                if 'pair' in cfg:
                    pair = cfg['pair'].split('/')[0].upper()
                    our_markets.add(pair)
            except:
                pass

        relevant = {}
        for k, v in all_mids.items():
            for m in our_markets:
                if m in k.upper():
                    relevant[k] = v
        return {'prices': relevant, 'note': 'Showing prices for configured markets. Pass symbols for specific lookups.'}

    except Exception as e:
        return {'error': str(e)}


def get_recent_fills_live(address: str = None, limit: int = 20) -> dict:
    """Get recent fills from Hyperliquid API (live, not just DB)"""
    try:
        info = _get_hl_info()

        if address:
            accounts = [{'address': address, 'label': 'Requested'}]
        else:
            accounts = _get_all_addresses()

        results = []
        for acct in accounts:
            addr = acct['address']
            if not addr:
                continue

            try:
                fills = info.user_fills(addr)
                recent = fills[:limit] if fills else []
                formatted = []
                for f in recent:
                    formatted.append({
                        'coin': f.get('coin'),
                        'side': f.get('side'),
                        'price': f.get('px'),
                        'size': f.get('sz'),
                        'fee': f.get('fee'),
                        'closed_pnl': f.get('closedPnl'),
                        'time': f.get('time'),
                        'crossed': f.get('crossed', False)
                    })

                if formatted:
                    results.append({
                        'label': acct['label'],
                        'address': addr[:10] + '...' + addr[-4:],
                        'fills': formatted
                    })
            except:
                pass

        return {'accounts_with_fills': results} if results else {'message': 'No recent fills found'}

    except Exception as e:
        return {'error': str(e)}


def get_asset_info(asset: str) -> dict:
    """Get detailed asset info including price_decimals, size_decimals, tick size, max leverage, and mark price."""
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        asset_upper = asset.upper()

        # --- Check perp markets first ---
        meta_ctx = info.post('/info', {'type': 'metaAndAssetCtxs'})
        universe = meta_ctx[0]['universe']
        contexts = meta_ctx[1]

        for i, market in enumerate(universe):
            if market['name'].upper() == asset_upper:
                ctx = contexts[i]
                mark_px_str = ctx.get('markPx', '0')
                sz_decimals = market.get('szDecimals', 2)
                max_leverage = market.get('maxLeverage', 50)

                # Determine price_decimals from markPx string
                if '.' in mark_px_str:
                    price_decimals = len(mark_px_str.rstrip('0').split('.')[1])
                    # Ensure at least what the string shows (don't strip trailing zeros too aggressively)
                    # Use the raw string length as the authoritative source
                    price_decimals_raw = len(mark_px_str.split('.')[1])
                else:
                    price_decimals = 0
                    price_decimals_raw = 0

                # Cross-check with 5-significant-figures rule
                try:
                    mark_price = float(mark_px_str)
                    if mark_price > 0:
                        import math
                        integer_digits = len(str(int(mark_price)))
                        sig_fig_decimals = max(0, 5 - integer_digits)
                        # Use the more conservative (higher precision) of the two
                        price_decimals = max(price_decimals, sig_fig_decimals)
                except (ValueError, OverflowError):
                    mark_price = 0.0

                tick_size = 10 ** (-price_decimals)

                return {
                    'found': True,
                    'type': 'perp',
                    'asset': market['name'],
                    'mark_price': mark_px_str,
                    'price_decimals': price_decimals,
                    'size_decimals': sz_decimals,
                    'tick_size': tick_size,
                    'max_leverage': max_leverage,
                    'funding_rate': ctx.get('funding'),
                    'open_interest': ctx.get('openInterest'),
                    'note': f"price_decimals={price_decimals} derived from markPx='{mark_px_str}' and 5-sig-fig rule"
                }

        # --- Check spot markets ---
        spot_meta = info.post('/info', {'type': 'spotMetaAndAssetCtxs'})
        spot_tokens = spot_meta[0].get('tokens', [])
        spot_universe = spot_meta[0].get('universe', [])
        spot_contexts = spot_meta[1]

        # Build a mapping from token index to token info
        token_by_index = {t['index']: t for t in spot_tokens}

        for i, pair in enumerate(spot_universe):
            tokens = pair.get('tokens', [])
            pair_name = pair.get('name', '')
            # Match against the base token name
            base_token_idx = tokens[0] if len(tokens) >= 2 else None
            base_token = token_by_index.get(base_token_idx, {})
            base_name = base_token.get('name', '')

            if base_name.upper() == asset_upper or asset_upper in pair_name.upper():
                ctx = spot_contexts[i] if i < len(spot_contexts) else {}
                mark_px_str = ctx.get('markPx') or ctx.get('midPx', '0')
                sz_decimals = base_token.get('szDecimals', 2)

                # Determine price_decimals from markPx string
                if '.' in mark_px_str:
                    price_decimals = len(mark_px_str.rstrip('0').split('.')[1])
                    price_decimals_raw = len(mark_px_str.split('.')[1])
                else:
                    price_decimals = 0
                    price_decimals_raw = 0

                # Cross-check with 5-significant-figures rule
                try:
                    mark_price = float(mark_px_str)
                    if mark_price > 0:
                        import math
                        integer_digits = len(str(int(mark_price)))
                        sig_fig_decimals = max(0, 5 - integer_digits)
                        price_decimals = max(price_decimals, sig_fig_decimals)
                except (ValueError, OverflowError):
                    mark_price = 0.0

                tick_size = 10 ** (-price_decimals)

                return {
                    'found': True,
                    'type': 'spot',
                    'asset': base_name,
                    'pair_name': pair_name,
                    'pair_index': pair.get('index'),
                    'mark_price': mark_px_str,
                    'price_decimals': price_decimals,
                    'size_decimals': sz_decimals,
                    'tick_size': tick_size,
                    'is_canonical': base_token.get('isCanonical', False),
                    'spot_coin_format': f"@{pair.get('index')}" if not base_token.get('isCanonical') else f"{base_name}/USDC",
                    'note': f"price_decimals={price_decimals} derived from markPx='{mark_px_str}' and 5-sig-fig rule"
                }

        return {'found': False, 'error': f'Asset {asset} not found in perp or spot markets'}

    except Exception as e:
        return {'found': False, 'error': str(e)}


def propose_new_config(config: dict, filename: str, description: str) -> dict:
    """Propose a new config file"""
    action_id = f"create_{filename}_{datetime.now().timestamp()}"
    pending_actions[action_id] = {
        'type': 'create_config',
        'action_id': action_id,
        'filename': filename,
        'config': config,
        'description': description,
        'proposed_at': datetime.now().isoformat()
    }

    return {
        'action_id': action_id,
        'type': 'create_config',
        'filename': filename,
        'config': config,
        'description': description,
        'message': f'Proposed new config: {filename}. User must confirm to create.'
    }


def propose_config_changes(filename: str, changes: dict, reason: str) -> dict:
    """Propose changes to an existing config"""
    current = read_config(filename)
    if not current.get('found'):
        return {'error': f'Config {filename} not found'}

    action_id = f"modify_{filename}_{datetime.now().timestamp()}"
    pending_actions[action_id] = {
        'type': 'modify_config',
        'action_id': action_id,
        'filename': filename,
        'current_config': current['config'],
        'changes': changes,
        'reason': reason,
        'proposed_at': datetime.now().isoformat()
    }

    return {
        'action_id': action_id,
        'type': 'modify_config',
        'filename': filename,
        'changes': changes,
        'reason': reason,
        'message': f'Proposed changes to {filename}. User must confirm to apply.'
    }


# Tool definitions for Claude
TOOLS = [
    {
        "name": "get_market_info",
        "description": "Look up market information from Hyperliquid including tick size, decimals, leverage limits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "The market symbol (e.g., 'HYPE', 'BTC', 'PURR')"}
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_spot_coin_id",
        "description": "Get the spot coin identifier format for Hyperliquid. Builder assets use @XXX format.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "The spot token symbol"}
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "read_config",
        "description": "Read an existing config file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "The config filename"}
            },
            "required": ["filename"]
        }
    },
    {
        "name": "list_configs",
        "description": "List all available config files.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_performance_metrics",
        "description": "Get trading performance metrics for a config.",
        "input_schema": {
            "type": "object",
            "properties": {
                "config_filename": {"type": "string", "description": "The config filename"},
                "window": {"type": "string", "enum": ["1h", "4h", "8h", "24h", "7d"], "description": "Time window"}
            },
            "required": ["config_filename"]
        }
    },
    {
        "name": "propose_new_config",
        "description": "Propose a new config file. Does NOT create it - presents to user for confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "config": {"type": "object", "description": "The complete config object"},
                "filename": {"type": "string", "description": "Suggested filename"},
                "description": {"type": "string", "description": "Brief description"}
            },
            "required": ["config", "filename", "description"]
        }
    },
    {
        "name": "propose_config_changes",
        "description": "Propose changes to an existing config. Does NOT modify - presents to user for confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "The config file to modify"},
                "changes": {"type": "object", "description": "Fields to change and new values"},
                "reason": {"type": "string", "description": "Why these changes are recommended"}
            },
            "required": ["filename", "changes", "reason"]
        }
    },
    {
        "name": "get_account_balances",
        "description": "Get account balances including USDC, spot tokens, account value, margin used, and withdrawable amount. Checks main account and all subaccounts by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Specific wallet address to check. If omitted, checks main account + all configured subaccounts."}
            }
        }
    },
    {
        "name": "get_open_positions",
        "description": "Get current open perpetual positions with entry price, size, unrealized PnL, leverage, and liquidation price. Checks all accounts by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Specific wallet address. If omitted, checks all configured accounts."}
            }
        }
    },
    {
        "name": "get_open_orders",
        "description": "Get all open/resting orders across main account and subaccounts, including HIP-3 builder markets (xyz, flx dexes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Specific wallet address. If omitted, checks all configured accounts."}
            }
        }
    },
    {
        "name": "get_current_prices",
        "description": "Get current mark/mid prices for markets. If no symbols given, returns prices for all configured trading pairs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of market symbols to look up (e.g., ['HYPE', 'BTC', 'ETH']). If omitted, returns prices for configured markets."
                }
            }
        }
    },
    {
        "name": "get_recent_fills_live",
        "description": "Get recent trade fills from Hyperliquid API (live data, not just local database). Shows coin, side, price, size, fee, and realized PnL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Specific wallet address. If omitted, checks all configured accounts."},
                "limit": {"type": "integer", "description": "Number of recent fills to return (default 20, max 100)"}
            }
        }
    },
    {
        "name": "get_asset_info",
        "description": "Get detailed asset information for any Hyperliquid perp or spot asset. Returns price_decimals, size_decimals (szDecimals), tick_size, max_leverage, and current mark price. Use this to determine correct decimal precision when creating configs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset": {"type": "string", "description": "The coin/asset name (e.g., 'HYPE', 'BTC', 'ETH', 'PURR', 'XMR')"}
            },
            "required": ["asset"]
        }
    }
]


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result"""
    if tool_name == "get_market_info":
        result = get_market_info(tool_input.get("symbol", ""))
    elif tool_name == "get_spot_coin_id":
        result = get_spot_coin_id(tool_input.get("symbol", ""))
    elif tool_name == "read_config":
        result = read_config(tool_input.get("filename", ""))
    elif tool_name == "list_configs":
        result = list_configs()
    elif tool_name == "get_performance_metrics":
        result = get_performance_metrics(
            tool_input.get("config_filename", ""),
            tool_input.get("window", "24h")
        )
    elif tool_name == "propose_new_config":
        result = propose_new_config(
            tool_input.get("config", {}),
            tool_input.get("filename", ""),
            tool_input.get("description", "")
        )
    elif tool_name == "propose_config_changes":
        result = propose_config_changes(
            tool_input.get("filename", ""),
            tool_input.get("changes", {}),
            tool_input.get("reason", "")
        )
    elif tool_name == "get_account_balances":
        result = get_account_balances(tool_input.get("address"))
    elif tool_name == "get_open_positions":
        result = get_open_positions(tool_input.get("address"))
    elif tool_name == "get_open_orders":
        result = get_open_orders(tool_input.get("address"))
    elif tool_name == "get_current_prices":
        result = get_current_prices(tool_input.get("symbols"))
    elif tool_name == "get_recent_fills_live":
        result = get_recent_fills_live(
            tool_input.get("address"),
            tool_input.get("limit", 20)
        )
    elif tool_name == "get_asset_info":
        result = get_asset_info(tool_input.get("asset", ""))
    else:
        result = {"error": f"Unknown tool: {tool_name}"}

    return json.dumps(result, indent=2)


# ============================================================================
# API ROUTES
# ============================================================================

@ai_bp.route('/settings', methods=['GET'])
def get_settings():
    """Get current AI settings"""
    settings = load_settings()
    api_key = settings.get('anthropic_api_key', '')
    if api_key:
        masked = api_key[:10] + '...' + api_key[-4:] if len(api_key) > 14 else '***'
    else:
        masked = ''

    return jsonify({
        'has_api_key': bool(api_key),
        'api_key_masked': masked,
        'model': settings.get('model', 'claude-sonnet-4-20250514')
    })


@ai_bp.route('/settings', methods=['POST'])
def update_settings():
    """Update AI settings"""
    data = request.json
    settings = load_settings()

    if 'anthropic_api_key' in data:
        settings['anthropic_api_key'] = data['anthropic_api_key']
    if 'model' in data:
        settings['model'] = data['model']

    save_settings(settings)
    return jsonify({'success': True})


@ai_bp.route('/chat', methods=['POST'])
def chat():
    """Chat with Claude"""
    settings = load_settings()
    api_key = settings.get('anthropic_api_key')

    if not api_key:
        return jsonify({'error': 'No API key configured. Go to Settings (gear icon) to add your Anthropic API key.'}), 400

    data = request.json
    user_message = data.get('message', '')
    conversation_history = data.get('history', [])

    if not user_message:
        return jsonify({'error': 'No message provided'}), 400

    try:
        client = anthropic.Anthropic(api_key=api_key)
        messages = conversation_history + [{"role": "user", "content": user_message}]

        system_prompt = """You are an AI assistant for a Hyperliquid trading bot dashboard. You help users:

1. CREATE new trading bot configs by looking up market info (tick sizes, decimals, spot coin IDs)
2. ANALYZE trading performance and suggest parameter improvements
3. EXPLAIN how the bots work and what settings do
4. CHECK account balances, positions, open orders, and recent fills
5. RECOMMEND config parameters based on actual account state (balances, position sizes, etc.)

IMPORTANT RULES:
- When creating configs, ALWAYS use get_asset_info first to get correct price_decimals, size_decimals, and tick sizes
- For spot markets, ALSO use get_spot_coin_id to get the correct format (@XXX or PAIR/USDC)
- NEVER directly create files - always use propose_new_config or propose_config_changes
- When proposing configs, show the user what you'll create and wait for confirmation
- When asked about balances, positions, or orders, use the live account tools to fetch real data
- When recommending order sizes or position limits, check balances first to suggest appropriate values
- Be concise but thorough in explanations

ACCOUNT TOOLS:
- get_account_balances: Check USDC balance, spot tokens, margin info (all accounts by default)
- get_open_positions: Current perp positions with PnL, leverage, liquidation price
- get_open_orders: All resting orders across accounts and dexes (main, xyz, flx)
- get_current_prices: Mark/mid prices for any market
- get_recent_fills_live: Recent trade executions from the exchange

MARKET DATA TOOLS:
- get_asset_info: Get price_decimals, size_decimals (szDecimals), tick_size, max_leverage, and current mark price for any perp or spot asset. Use this FIRST when creating configs to get the correct decimal precision. Example: get_asset_info("HYPE") returns price_decimals=4, size_decimals=2, tick_size=0.0001, etc.
- get_market_info: Basic market metadata lookup (universe entry)
- get_spot_coin_id: Get the spot coin identifier format (@XXX for builder, PAIR/USDC for canonical)

CONFIG SCHEMAS - You MUST use these EXACT field names and structures. Do NOT invent field names.
CRITICAL: NEVER truncate wallet addresses. Always use the FULL 42-character hex address (e.g., "0x1234567890abcdef1234567890abcdef12345678"), never shortened forms like "0x1234...5678".

GRID TRADER CONFIG (for grid bots):
{
  "market": "HYPE",              // coin name, or "xyz:COPPER" for HIP-3
  "dex": "",                     // "" for main, "xyz" or "flx" for HIP-3 builder markets
  "description": "...",
  "grid": {
    "spacing_pct": 0.5,          // % between grid levels (e.g., 0.5 = 0.5%)
    "num_levels_each_side": 5,   // number of orders above AND below current price
    "order_size_usd": 25,        // USD per order
    "rebalance_threshold_pct": 2.0,  // rebalance when price moves this % from center
    "bias": "neutral"            // MUST be "long", "short", or "neutral" (strings only, NOT numeric)
  },
  "position": {
    "target_position_usd": 0,    // ideal position in USD (0 = neutral, positive = long bias)
    "max_position_usd": 300,     // max allowed position
    "leverage": 3                // leverage multiplier
  },
  "timing": { "fill_check_seconds": 5, "health_check_seconds": 60 },
  "safety": {
    "max_open_orders": 12, "emergency_stop_loss_pct": -15.0,
    "min_margin_ratio_pct": 10.0, "pause_on_high_volatility": true,
    "volatility_threshold_pct": 5.0, "max_account_drawdown_pct": -20.0,
    "close_position_on_emergency": true
  },
  "exchange": { "price_decimals": 4, "size_decimals": 2 },
  "account": { "subaccount_address": null, "is_subaccount": false }
}

PERP MARKET MAKER CONFIG:
{
  "market": "ICP",               // coin name, or "xyz:COPPER" for HIP-3
  "dex": "",
  "description": "...",
  "trading": {
    "base_spread_bps": 50, "min_spread_bps": 8, "max_spread_bps": 200,
    "base_order_size": 15,       // USD per order
    "min_order_size": 5, "max_order_size": 50,
    "update_threshold_bps": 5, "smart_order_mgmt_enabled": true,
    "inventory_skew_bps_per_unit": 20, "funding_skew_bps": 150,
    "profit_taking_enabled": true
  },
  "position": {
    "target_position_usd": 0, "max_position_usd": 100, "leverage": 5
  },
  "timing": { "quote_interval_seconds": 10, "health_check_seconds": 60 },
  "safety": {
    "max_open_orders": 6, "emergency_stop_loss_pct": -20.0,
    "min_margin_ratio_pct": 10.0, "pause_on_high_volatility": true,
    "volatility_threshold_pct": 5.0, "max_account_drawdown_pct": -25.0,
    "close_position_on_emergency": true
  },
  "exchange": { "price_decimals": 4, "size_decimals": 2 },
  "account": { "subaccount_address": null, "is_subaccount": false }
}

SPOT MARKET MAKER CONFIG:
{
  "pair": "XMR1/USDC",
  "description": "...",
  "trading": {
    "base_spread_bps": 50, "min_spread_bps": 20, "max_spread_bps": 200,
    "base_order_size": 5, "min_order_size": 1, "max_order_size": 20,
    "update_threshold_bps": 10, "smart_order_mgmt_enabled": true,
    "inventory_skew_bps_per_unit": 25
  },
  "position": { "max_position_size": 100, "target_position": 0 },
  "timing": { "quote_interval_seconds": 10, "health_check_seconds": 60, "max_oracle_age_seconds": 120 },
  "safety": {
    "max_open_orders": 4, "circuit_breaker_bps": 500,
    "pause_on_high_volatility": true, "volatility_threshold_pct": 3.0
  },
  "exchange": {
    "spot_coin": "@260",          // "@XXX" for builder, "PAIR/USDC" for canonical
    "spot_coin_order": "@260",
    "perp_coin": "XMR",           // perp oracle source
    "price_decimals": 2, "size_decimals": 2
  },
  "account": { "subaccount_address": null, "is_subaccount": false }
}

CRITICAL RULES:
- Use ONLY the field names shown above. Do NOT invent fields like "grid_spacing_pct" or "levels".
- Grid bias MUST be a string: "long", "short", or "neutral". NEVER use numeric values like 0.7.
- When proposing changes, make sure the values in your response text MATCH the actual values you send.
- Always read an existing config with read_config before proposing modifications.

When asked to create a config, follow these steps:
1. Ask clarifying questions if needed (which account/subaccount, position limits, etc.)
2. Look up market info with tools to get correct decimals
3. Check account balances to recommend appropriate order sizes
4. Build a complete config using the EXACT schemas above
5. Use propose_new_config to show it to the user
6. Explain what each key setting does"""

        response = client.messages.create(
            model=settings.get('model', 'claude-sonnet-4-20250514'),
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages
        )

        # Handle tool use loop
        while response.stop_reason == "tool_use":
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    tool_result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_result
                    })

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

            response = client.messages.create(
                model=settings.get('model', 'claude-sonnet-4-20250514'),
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=messages
            )

        response_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                response_text += block.text

        pending = [v for v in pending_actions.values()]

        return jsonify({
            'response': response_text,
            'pending_actions': pending[-5:] if pending else []
        })

    except anthropic.APIError as e:
        return jsonify({'error': f'API error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@ai_bp.route('/confirm_action', methods=['POST'])
def confirm_action():
    """Confirm and execute a pending action"""
    data = request.json
    action_id = data.get('action_id')

    if not action_id or action_id not in pending_actions:
        return jsonify({'error': 'Invalid or expired action ID'}), 400

    action = pending_actions.pop(action_id)

    try:
        if action['type'] == 'create_config':
            filepath = os.path.join(CONFIG_DIR, action['filename'])
            with open(filepath, 'w') as f:
                json.dump(action['config'], f, indent=2)

            return jsonify({
                'success': True,
                'message': f"Created {action['filename']}",
                'filepath': filepath
            })

        elif action['type'] == 'modify_config':
            filepath = os.path.join(CONFIG_DIR, action['filename'])

            with open(filepath, 'r') as f:
                config = json.load(f)

            def deep_merge(base, changes):
                for key, value in changes.items():
                    if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                        deep_merge(base[key], value)
                    else:
                        base[key] = value

            deep_merge(config, action['changes'])

            with open(filepath, 'w') as f:
                json.dump(config, f, indent=2)

            return jsonify({
                'success': True,
                'message': f"Updated {action['filename']}",
                'filepath': filepath
            })

        return jsonify({'error': 'Unknown action type'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@ai_bp.route('/cancel_action', methods=['POST'])
def cancel_action():
    """Cancel a pending action"""
    data = request.json
    action_id = data.get('action_id')

    if action_id in pending_actions:
        del pending_actions[action_id]

    return jsonify({'success': True})


@ai_bp.route('/pending_actions', methods=['GET'])
def get_pending_actions():
    """Get all pending actions"""
    return jsonify({'actions': list(pending_actions.values())})


# ============================================================================
# SETTINGS PAGE
# ============================================================================

SETTINGS_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>AI Settings - Perp Lobster</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', monospace;
            background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #0f0f1a 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 40px;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
        }
        .header {
            margin-bottom: 40px;
        }
        .header h1 {
            color: #00ffff;
            margin-bottom: 10px;
        }
        .header a {
            color: #888;
            text-decoration: none;
        }
        .header a:hover { color: #00ffff; }
        .card {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(0, 255, 255, 0.2);
            border-radius: 8px;
            padding: 25px;
            margin-bottom: 20px;
        }
        .card h2 {
            color: #00ffff;
            font-size: 1.1rem;
            margin-bottom: 20px;
        }
        label {
            display: block;
            color: #aaa;
            font-size: 0.85rem;
            margin-bottom: 8px;
        }
        input, select {
            width: 100%;
            padding: 12px;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(0, 255, 255, 0.3);
            border-radius: 6px;
            color: #e0e0e0;
            font-family: inherit;
            font-size: 0.95rem;
            margin-bottom: 15px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #00ffff;
        }
        button {
            padding: 12px 24px;
            background: linear-gradient(135deg, #00aaaa, #008888);
            border: none;
            border-radius: 6px;
            color: white;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover {
            background: linear-gradient(135deg, #00cccc, #00aaaa);
        }
        .status {
            padding: 12px;
            border-radius: 6px;
            margin-top: 15px;
            font-size: 0.9rem;
        }
        .status.success {
            background: rgba(0, 200, 0, 0.2);
            border: 1px solid rgba(0, 200, 0, 0.3);
            color: #4ade80;
        }
        .status.warning {
            background: rgba(200, 100, 0, 0.2);
            border: 1px solid rgba(200, 100, 0, 0.3);
            color: #fbbf24;
        }
        .status.error {
            background: rgba(200, 50, 50, 0.2);
            border: 1px solid rgba(200, 50, 50, 0.3);
            color: #f87171;
        }
        .info-text {
            font-size: 0.8rem;
            color: #666;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚙️ AI Assistant Settings</h1>
            <a href="/">&larr; Back to Dashboard</a>
        </div>

        <div class="card">
            <h2>Anthropic API Key</h2>
            <label>API Key</label>
            <input type="password" id="apiKey" placeholder="sk-ant-api03-...">
            <p class="info-text">Get your API key from <a href="https://console.anthropic.com/" target="_blank" style="color: #00ffff;">console.anthropic.com</a></p>

            <label style="margin-top: 20px;">Model</label>
            <select id="model">
                <option value="claude-sonnet-4-20250514">Claude Sonnet 4 (Recommended)</option>
                <option value="claude-opus-4-20250514">Claude Opus 4 (Most capable)</option>
                <option value="claude-3-5-haiku-20241022">Claude 3.5 Haiku (Fastest)</option>
            </select>

            <button onclick="saveSettings()">Save Settings</button>

            <div id="status"></div>
        </div>

        <div class="card">
            <h2>Current Status</h2>
            <div id="currentStatus">Loading...</div>
        </div>
    </div>

    <script>
        async function loadSettings() {
            try {
                const resp = await fetch('/ai/settings');
                const data = await resp.json();

                const statusEl = document.getElementById('currentStatus');
                if (data.has_api_key) {
                    statusEl.innerHTML = `
                        <div class="status success">
                            ✓ API key configured: ${data.api_key_masked}<br>
                            Model: ${data.model}
                        </div>
                    `;
                    document.getElementById('model').value = data.model;
                } else {
                    statusEl.innerHTML = `
                        <div class="status warning">
                            No API key configured. Add your key above to enable the AI assistant.
                        </div>
                    `;
                }
            } catch (e) {
                document.getElementById('currentStatus').innerHTML = `
                    <div class="status error">Error loading settings: ${e.message}</div>
                `;
            }
        }

        async function saveSettings() {
            const apiKey = document.getElementById('apiKey').value.trim();
            const model = document.getElementById('model').value;

            const payload = { model };
            if (apiKey) {
                payload.anthropic_api_key = apiKey;
            }

            try {
                const resp = await fetch('/ai/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (resp.ok) {
                    document.getElementById('status').innerHTML = `
                        <div class="status success">Settings saved successfully!</div>
                    `;
                    document.getElementById('apiKey').value = '';
                    loadSettings();
                } else {
                    throw new Error('Failed to save');
                }
            } catch (e) {
                document.getElementById('status').innerHTML = `
                    <div class="status error">Error saving settings: ${e.message}</div>
                `;
            }
        }

        loadSettings();
    </script>
</body>
</html>
"""

@ai_bp.route('/')
def settings_page():
    """Render the settings page"""
    return render_template_string(SETTINGS_PAGE_HTML)


# ============================================================================
# SLIDE-OUT CHAT PANEL COMPONENT
# This HTML/CSS/JS can be injected into any page
# ============================================================================

def get_chat_panel_html():
    """Returns the HTML/CSS/JS for the slide-out chat panel"""
    return """
<!-- AI Chat Panel Toggle Button -->
<button id="aiChatToggle" onclick="toggleAiChat()" title="AI Assistant">
    🤖
</button>

<!-- AI Chat Slide-out Panel -->
<div id="aiChatPanel" class="ai-chat-panel">
    <div class="ai-chat-header">
        <span>🤖 AI Assistant</span>
        <div>
            <button onclick="clearAiChat()" class="ai-clear-btn" title="Clear chat">Clear</button>
            <a href="/ai" class="ai-settings-link" title="Settings">⚙️</a>
            <button onclick="toggleAiChat()" class="ai-close-btn">✕</button>
        </div>
    </div>

    <div class="ai-chat-messages" id="aiChatMessages">
        <div class="ai-message ai-system">
            I can help you create configs and analyze your strategies. Try:
            <br>• "Create a perp config for HYPE"
            <br>• "What's the tick size for BTC?"
            <br>• "Analyze my trading performance"
        </div>
    </div>

    <div class="ai-pending-actions" id="aiPendingActions"></div>

    <div class="ai-chat-input">
        <textarea id="aiChatInput" placeholder="Ask me anything..." rows="2"></textarea>
        <button id="aiSendBtn" onclick="sendAiMessage()">Send</button>
    </div>
</div>

<style>
/* Chat Toggle Button */
#aiChatToggle {
    position: fixed;
    bottom: 90px;  /* Above emergency footer */
    right: 20px;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border: none;
    color: white;
    font-size: 24px;
    cursor: pointer;
    box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
    z-index: 10000;  /* Above emergency footer */
    transition: all 0.3s;
}
#aiChatToggle:hover {
    transform: scale(1.1);
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.6);
}
#aiChatToggle.active {
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
}

/* Chat Panel */
.ai-chat-panel {
    position: fixed;
    top: 0;
    right: -420px;
    width: 400px;
    height: 100vh;
    background: linear-gradient(180deg, #0d0d15 0%, #1a1a2e 100%);
    border-left: 1px solid rgba(99, 102, 241, 0.3);
    display: flex;
    flex-direction: column;
    z-index: 9999;
    transition: right 0.3s ease;
    box-shadow: -5px 0 30px rgba(0, 0, 0, 0.5);
}
.ai-chat-panel.open {
    right: 0;
}

.ai-chat-header {
    padding: 15px 20px;
    background: rgba(99, 102, 241, 0.1);
    border-bottom: 1px solid rgba(99, 102, 241, 0.2);
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: #a5b4fc;
    font-weight: 600;
}
.ai-settings-link {
    color: #888;
    text-decoration: none;
    margin-right: 15px;
    font-size: 18px;
}
.ai-settings-link:hover { color: #a5b4fc; }
.ai-close-btn {
    background: none;
    border: none;
    color: #888;
    font-size: 20px;
    cursor: pointer;
}
.ai-close-btn:hover { color: #fff; }

.ai-chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 15px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.ai-message {
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 0.9rem;
    line-height: 1.5;
    max-width: 90%;
}
.ai-message.ai-user {
    align-self: flex-end;
    background: rgba(99, 102, 241, 0.3);
    border: 1px solid rgba(99, 102, 241, 0.4);
    color: #e0e0e0;
}
.ai-message.ai-assistant {
    align-self: flex-start;
    background: rgba(30, 30, 50, 0.8);
    border: 1px solid rgba(100, 100, 150, 0.3);
    color: #d0d0d0;
}
.ai-message.ai-system {
    align-self: center;
    background: rgba(50, 50, 70, 0.5);
    border: 1px solid rgba(100, 100, 130, 0.3);
    color: #aaa;
    font-size: 0.85rem;
    text-align: center;
}
.ai-message.ai-error {
    background: rgba(220, 50, 50, 0.2);
    border: 1px solid rgba(220, 80, 80, 0.3);
    color: #f87171;
}

.ai-message pre {
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 4px;
    padding: 10px;
    margin: 8px 0;
    overflow-x: auto;
    font-size: 0.8rem;
}
.ai-message code {
    background: rgba(0, 0, 0, 0.3);
    padding: 2px 5px;
    border-radius: 3px;
    font-size: 0.85em;
}
.ai-message pre code {
    background: none;
    padding: 0;
}

/* Pending Actions */
.ai-pending-actions {
    border-top: 1px solid rgba(99, 102, 241, 0.2);
    max-height: 200px;
    overflow-y: auto;
}
.ai-pending-action {
    padding: 12px 15px;
    background: rgba(99, 102, 241, 0.1);
    border-bottom: 1px solid rgba(99, 102, 241, 0.1);
}
.ai-pending-action h4 {
    color: #a5b4fc;
    font-size: 0.85rem;
    margin-bottom: 5px;
}
.ai-pending-action .filename {
    color: #888;
    font-size: 0.8rem;
    margin-bottom: 8px;
}
.ai-pending-action .actions {
    display: flex;
    gap: 8px;
}
.ai-pending-action button {
    padding: 5px 12px;
    border-radius: 4px;
    border: none;
    font-size: 0.8rem;
    cursor: pointer;
}
.ai-pending-action .confirm {
    background: #10b981;
    color: white;
}
.ai-pending-action .cancel {
    background: rgba(100, 100, 100, 0.3);
    color: #aaa;
    border: 1px solid rgba(100, 100, 100, 0.3);
}

.ai-chat-input {
    padding: 12px;
    background: rgba(0, 0, 0, 0.3);
    border-top: 1px solid rgba(99, 102, 241, 0.2);
    display: flex;
    gap: 8px;
}
.ai-chat-input textarea {
    flex: 1;
    background: rgba(0, 0, 0, 0.5);
    border: 1px solid rgba(99, 102, 241, 0.3);
    border-radius: 6px;
    padding: 10px;
    color: #e0e0e0;
    font-family: inherit;
    font-size: 0.9rem;
    resize: none;
}
.ai-chat-input textarea:focus {
    outline: none;
    border-color: #6366f1;
}
.ai-chat-input button {
    padding: 10px 18px;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    border: none;
    border-radius: 6px;
    color: white;
    font-weight: 600;
    cursor: pointer;
}
.ai-chat-input button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* Scrollbar */
.ai-chat-messages::-webkit-scrollbar,
.ai-pending-actions::-webkit-scrollbar {
    width: 6px;
}
.ai-chat-messages::-webkit-scrollbar-track,
.ai-pending-actions::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.2);
}
.ai-chat-messages::-webkit-scrollbar-thumb,
.ai-pending-actions::-webkit-scrollbar-thumb {
    background: rgba(99, 102, 241, 0.3);
    border-radius: 3px;
}

/* Loading spinner (button) */
.ai-loading {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid rgba(99, 102, 241, 0.3);
    border-top-color: #6366f1;
    border-radius: 50%;
    animation: aiSpin 1s linear infinite;
}
@keyframes aiSpin {
    to { transform: rotate(360deg); }
}

/* Thinking indicator in chat */
.ai-thinking {
    align-self: flex-start;
    background: rgba(30, 30, 50, 0.8);
    border: 1px solid rgba(99, 102, 241, 0.25);
    border-radius: 8px;
    padding: 12px 16px;
    max-width: 90%;
    font-size: 0.9rem;
}
.ai-thinking-header {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #a5b4fc;
    font-weight: 600;
    font-size: 0.85rem;
    margin-bottom: 8px;
}
.ai-thinking-header .ai-pulse {
    width: 8px;
    height: 8px;
    background: #6366f1;
    border-radius: 50%;
    animation: aiPulse 1.5s ease-in-out infinite;
}
@keyframes aiPulse {
    0%, 100% { opacity: 0.4; transform: scale(0.8); }
    50% { opacity: 1; transform: scale(1.2); }
}
.ai-thinking-dots {
    display: inline-flex;
    gap: 3px;
    margin-left: 2px;
}
.ai-thinking-dots span {
    width: 4px;
    height: 4px;
    background: #6366f1;
    border-radius: 50%;
    animation: aiDotBounce 1.4s ease-in-out infinite;
}
.ai-thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.ai-thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes aiDotBounce {
    0%, 80%, 100% { opacity: 0.3; transform: translateY(0); }
    40% { opacity: 1; transform: translateY(-4px); }
}

/* Clear chat button */
.ai-clear-btn {
    background: none;
    border: none;
    color: #555;
    font-size: 13px;
    cursor: pointer;
    margin-right: 8px;
    padding: 2px 6px;
    border-radius: 4px;
}
.ai-clear-btn:hover { color: #f87171; background: rgba(248, 113, 113, 0.1); }
</style>

<script>
// AI Chat State
let aiChatHistory = [];
let aiIsLoading = false;
let aiThinkingEl = null;

// ---- Persistence via sessionStorage ----
const AI_STORAGE_KEY = 'perplobster_ai_chat';

function saveAiState() {
    const messagesEl = document.getElementById('aiChatMessages');
    // Save history and rendered HTML (excluding thinking bubble)
    const clone = messagesEl.cloneNode(true);
    const thinking = clone.querySelector('.ai-thinking');
    if (thinking) thinking.remove();
    sessionStorage.setItem(AI_STORAGE_KEY, JSON.stringify({
        history: aiChatHistory,
        html: clone.innerHTML
    }));
}

function restoreAiState() {
    try {
        const saved = sessionStorage.getItem(AI_STORAGE_KEY);
        if (!saved) return false;
        const state = JSON.parse(saved);
        if (state.history && state.history.length > 0) {
            aiChatHistory = state.history;
            const messagesEl = document.getElementById('aiChatMessages');
            messagesEl.innerHTML = state.html;
            messagesEl.scrollTop = messagesEl.scrollHeight;
            return true;
        }
    } catch (e) {}
    return false;
}

function clearAiChat() {
    aiChatHistory = [];
    sessionStorage.removeItem(AI_STORAGE_KEY);
    const messagesEl = document.getElementById('aiChatMessages');
    messagesEl.innerHTML = `
        <div class="ai-message ai-system">
            I can help you create configs and analyze your strategies. Try:
            <br>• "Create a perp config for HYPE"
            <br>• "What's the tick size for BTC?"
            <br>• "Analyze my trading performance"
        </div>
    `;
}

// ---- Thinking indicator ----
function showAiThinking() {
    const messagesEl = document.getElementById('aiChatMessages');
    aiThinkingEl = document.createElement('div');
    aiThinkingEl.className = 'ai-thinking';
    aiThinkingEl.innerHTML = `
        <div class="ai-thinking-header">
            <div class="ai-pulse"></div>
            Thinking<span class="ai-thinking-dots"><span></span><span></span><span></span></span>
        </div>
    `;
    messagesEl.appendChild(aiThinkingEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function hideAiThinking() {
    if (aiThinkingEl) {
        aiThinkingEl.remove();
        aiThinkingEl = null;
    }
}

// ---- Core chat functions ----
function toggleAiChat() {
    const panel = document.getElementById('aiChatPanel');
    const toggle = document.getElementById('aiChatToggle');
    panel.classList.toggle('open');
    toggle.classList.toggle('active');
}

function addAiMessage(role, content) {
    const messagesEl = document.getElementById('aiChatMessages');
    const msgEl = document.createElement('div');
    msgEl.className = 'ai-message ai-' + role;

    // Convert markdown code blocks
    let html = content;
    html = html.replace(/```(\\w*)\\n([\\s\\S]*?)```/g, '<pre><code>$2</code></pre>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\\n/g, '<br>');

    msgEl.innerHTML = html;
    messagesEl.appendChild(msgEl);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    // Persist after each message
    saveAiState();
}

async function sendAiMessage() {
    if (aiIsLoading) return;

    const input = document.getElementById('aiChatInput');
    const message = input.value.trim();
    if (!message) return;

    addAiMessage('user', message);
    input.value = '';

    aiIsLoading = true;
    const btn = document.getElementById('aiSendBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="ai-loading"></span>';

    // Show thinking indicator
    showAiThinking();

    try {
        const resp = await fetch('/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                history: aiChatHistory
            })
        });

        const data = await resp.json();

        // Remove thinking indicator
        hideAiThinking();

        if (data.error) {
            addAiMessage('error', data.error);
        } else {
            aiChatHistory.push({ role: 'user', content: message });
            aiChatHistory.push({ role: 'assistant', content: data.response });
            addAiMessage('assistant', data.response);

            if (data.pending_actions && data.pending_actions.length > 0) {
                renderAiPendingActions(data.pending_actions);
            }
        }
    } catch (e) {
        hideAiThinking();
        addAiMessage('error', 'Failed to send: ' + e.message);
    } finally {
        aiIsLoading = false;
        btn.disabled = false;
        btn.innerHTML = 'Send';
    }
}

function renderAiPendingActions(actions) {
    const container = document.getElementById('aiPendingActions');
    if (!actions || actions.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = actions.map(a => `
        <div class="ai-pending-action">
            <h4>${a.type === 'create_config' ? '📄 Create' : '✏️ Modify'}: ${a.filename}</h4>
            <div class="actions">
                <button class="confirm" onclick="confirmAiAction('${a.action_id}')">✓ Confirm</button>
                <button class="cancel" onclick="cancelAiAction('${a.action_id}')">✗ Cancel</button>
            </div>
        </div>
    `).join('');
}

async function confirmAiAction(actionId) {
    try {
        const resp = await fetch('/ai/confirm_action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action_id: actionId })
        });
        const data = await resp.json();

        if (data.success) {
            addAiMessage('system', '✓ ' + data.message);
            fetchAiPendingActions();
        } else {
            addAiMessage('error', data.error || 'Failed');
        }
    } catch (e) {
        addAiMessage('error', 'Error: ' + e.message);
    }
}

async function cancelAiAction(actionId) {
    await fetch('/ai/cancel_action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId })
    });
    addAiMessage('system', 'Action cancelled');
    fetchAiPendingActions();
}

async function fetchAiPendingActions() {
    try {
        const resp = await fetch('/ai/pending_actions');
        const data = await resp.json();
        renderAiPendingActions(data.actions);
    } catch (e) {}
}

// Handle Enter key
document.getElementById('aiChatInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAiMessage();
    }
});

// ---- Init: restore state & load pending actions ----
restoreAiState();
fetchAiPendingActions();
</script>
"""


# Route to get the chat panel HTML (for AJAX injection)
@ai_bp.route('/chat-panel')
def chat_panel():
    """Return the chat panel HTML for injection into other pages"""
    return get_chat_panel_html()