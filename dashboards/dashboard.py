#!/usr/bin/env python3
"""
Perp Lobster - Unified Dashboard
Auto-discovers all trading pairs and creates dashboards for each

Usage:
    cd perplobster
    python dashboards/dashboard.py
    Then open: http://localhost:5050
"""

import os
import sys
import json
import sqlite3

# Monkey-patch for eventlet BEFORE other imports
try:
    import eventlet
    eventlet.monkey_patch()
    EVENTLET_AVAILABLE = True
except ImportError:
    EVENTLET_AVAILABLE = False

from flask import Flask, render_template_string, jsonify, redirect, request

# Try to import Flask-SocketIO for real-time features
try:
    from flask_socketio import SocketIO, emit
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    print("Warning: flask-socketio not installed. Real-time features disabled.")
    print("Run: pip install flask-socketio eventlet")

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from config_discovery import ConfigDiscovery
from dashboard_blueprint import create_dashboard_blueprint
from dashboard_perp_blueprint import create_perp_dashboard_blueprint
from config_editor_blueprint import create_config_editor_blueprint
from ai_assistant_blueprint import ai_bp
from bot_manager import get_bot_manager

app = Flask(__name__)
app.config['SECRET_KEY'] = 'perplobster-secret-key'

# Initialize SocketIO if available
if SOCKETIO_AVAILABLE:
    # Use eventlet for proper WebSocket support, fall back to threading
    async_mode = 'eventlet' if EVENTLET_AVAILABLE else 'threading'
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)
    print(f"SocketIO initialized with async_mode={async_mode}")
else:
    socketio = None

# Paths relative to project root
VIBETRADERS_ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(VIBETRADERS_ROOT, 'config')
EXAMPLES_DIR = os.path.join(CONFIG_DIR, 'examples')
BOTS_DIR = os.path.join(VIBETRADERS_ROOT, 'bots')
DATABASE_PATH = os.path.join(VIBETRADERS_ROOT, 'trading_data.db')
MAIN_CONFIG_PATH = os.path.join(VIBETRADERS_ROOT, 'config.json')

# Load main account address from .env (falls back to config.json)
from credentials import get_credentials
main_account = get_credentials().get('account_address') or 'Not configured'

# Discover all trading pairs
discovery = ConfigDiscovery(config_dir=CONFIG_DIR)
ALL_PAIRS = discovery.get_all_pairs()

print(f"")
print(f"=" * 80)
print(f"PERP LOBSTER DASHBOARD")
print(f"=" * 80)
print(f"")
print(f"Config directory: {CONFIG_DIR}")
print(f"Database: {DATABASE_PATH}")
print(f"")

if ALL_PAIRS:
    print(f"Discovered {len(ALL_PAIRS)} trading pairs:")
    for pair_info in ALL_PAIRS:
        print(f"  - {pair_info['pair']:15s} ({pair_info['type']}) -> http://localhost:5050/{pair_info['route']}")
else:
    print(f"No trading pairs discovered in {CONFIG_DIR}")
    print(f"Add config files to config/examples/ and copy to config/ to get started")

print(f"")
print(f"Landing page: http://localhost:5050/")
print(f"Accounts: http://localhost:5050/accounts")
print(f"Config Manager: http://localhost:5050/config")
print(f"=" * 80)
print(f"")

# Register config editor blueprint
config_editor_bp = create_config_editor_blueprint(
    config_dir=CONFIG_DIR,
    examples_dir=EXAMPLES_DIR,
    bots_dir=BOTS_DIR
)
app.register_blueprint(config_editor_bp)
print(f"  Registered CONFIG EDITOR: /config")

# Register AI assistant blueprint
app.register_blueprint(ai_bp)
print(f"  Registered AI ASSISTANT: /ai")

# Register blueprints for each discovered pair
for pair_info in ALL_PAIRS:
    try:
        if pair_info['type'] == 'spot':
            bp = create_dashboard_blueprint(
                pair_name=pair_info['pair'],
                route_prefix=pair_info['route'],
                database_path=DATABASE_PATH
            )
            app.register_blueprint(bp)
            print(f"  Registered SPOT dashboard: /{pair_info['route']}")
        elif pair_info['type'] == 'perp':
            # Pass base market name (e.g., "BTC") - blueprint handles "-PERP" suffix
            original_market = pair_info.get('market_name', pair_info['base_token'])
            # Extract just the filename for bot control
            config_filepath = pair_info.get('config_file', '')
            config_filename = os.path.basename(config_filepath) if config_filepath else None
            bp = create_perp_dashboard_blueprint(
                market_name=original_market,
                route_prefix=pair_info['route'],
                database_path=DATABASE_PATH,
                config_file=config_filename
            )
            app.register_blueprint(bp)
            print(f"  Registered PERP dashboard: /{pair_info['route']} (config: {config_filename})")
        elif pair_info['type'] == 'grid':
            # Grid bots store fills with raw market name (e.g., "xyz:GOLD")
            # Pass the raw market name so the blueprint queries correctly
            raw_market_name = pair_info.get('market_name', pair_info['base_token'])
            config_filepath = pair_info.get('config_file', '')
            config_filename = os.path.basename(config_filepath) if config_filepath else None
            bp = create_perp_dashboard_blueprint(
                market_name=raw_market_name,
                route_prefix=pair_info['route'],
                database_path=DATABASE_PATH,
                config_file=config_filename,
                is_grid=True  # Tell blueprint to use raw market name for DB queries
            )
            app.register_blueprint(bp)
            print(f"  Registered GRID dashboard: /{pair_info['route']} (market: {raw_market_name}, config: {config_filename})")
    except Exception as e:
        print(f"  WARNING: Could not register {pair_info['pair']}: {e}")


# ============================================================================
# COMMON FOOTER (injected into all HTML pages via after_request)
# ============================================================================

COMMON_FOOTER = '''
<!-- Common Footer -->
<div style="height: 100px;"></div>
<div id="vt-footer" style="
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: linear-gradient(180deg, transparent 0%, #0a0a0f 40%);
    padding: 25px 20px 12px 20px;
    text-align: center;
    z-index: 9998;
">
    <button id="emergencyBtn" onclick="window.__vtEmergencyStop()" style="
        padding: 10px 35px;
        font-size: 13px;
        font-weight: bold;
        background: #dc2626;
        color: white;
        border: 2px solid #ff4444;
        border-radius: 8px;
        cursor: pointer;
        font-family: inherit;
        transition: all 0.2s;
    " onmouseover="this.style.background='#b91c1c'" onmouseout="this.style.background='#dc2626'">
        EMERGENCY STOP
    </button>
    <div style="font-size: 10px; color: #555; margin-top: 6px;">
        Kills all bots + cancels all orders &nbsp;|&nbsp;
        <a href="/emergency" style="color: #666; text-decoration: none;">Full emergency page</a> &nbsp;|&nbsp;
        <a href="/terms" style="color: #666; text-decoration: none;">Terms &amp; Disclaimer</a> &nbsp;|&nbsp;
        <span style="color: #555;">Powered by <a href="https://vibetrade.cc" style="color: #666; text-decoration: none;">Vibetrade.cc</a></span>
    </div>
</div>
<script>
window.__vtEmergencyStop = async function() {
    const btn = document.getElementById('emergencyBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'STOPPING...'; }
    try {
        const resp = await fetch('/api/emergency_stop', { method: 'POST' });
        const data = await resp.json();
        let msg = 'EMERGENCY STOP COMPLETE\\n';
        msg += 'Killed ' + data.processes_killed + ' process(es)\\n';
        msg += 'Cancelled ' + data.orders_cancelled + ' order(s)';
        alert(msg);
        if (btn) { btn.textContent = 'STOPPED'; btn.style.background = '#059669'; }
        // Trigger page-specific refresh callbacks if they exist
        if (typeof checkBotStatus === 'function') checkBotStatus();
        if (typeof refreshAllStatus === 'function') refreshAllStatus();
        if (typeof updateRunningCount === 'function') updateRunningCount();
    } catch (err) {
        alert('Error: ' + err.message);
        if (btn) { btn.disabled = false; btn.textContent = 'EMERGENCY STOP'; }
    }
};
</script>

<!-- AI Chat Panel (loaded dynamically) -->
<div id="aiChatContainer"></div>
<script>
fetch('/ai/chat-panel')
    .then(r => r.text())
    .then(html => {
        const container = document.getElementById('aiChatContainer');
        container.innerHTML = html;
        container.querySelectorAll('script').forEach(oldScript => {
            const newScript = document.createElement('script');
            newScript.textContent = oldScript.textContent;
            oldScript.parentNode.replaceChild(newScript, oldScript);
        });
    })
    .catch(e => console.error('AI chat panel error:', e));
</script>
'''

# Pages that should NOT get the common footer injected
_NO_FOOTER_PATHS = {'/ai/chat-panel', '/emergency'}


@app.after_request
def inject_common_footer(response):
    """Inject the shared footer (emergency stop + AI chat) into all HTML pages"""
    if (response.content_type
            and 'text/html' in response.content_type
            and request.path not in _NO_FOOTER_PATHS
            and not request.path.startswith('/api/')):
        html = response.get_data(as_text=True)
        if '</body>' in html and 'id="vt-footer"' not in html:
            html = html.replace('</body>', COMMON_FOOTER + '</body>')
            response.set_data(html)
    return response


# ============================================================================
# TERMS & DISCLAIMER PAGE
# ============================================================================

TERMS_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Terms & Disclaimer - Perp Lobster</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', monospace;
            background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #0f0f1a 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 30px;
        }
        .container { max-width: 800px; margin: 0 auto; }
        .header { margin-bottom: 30px; }
        .header h1 { color: #00ffff; margin-bottom: 8px; font-size: 1.5rem; }
        .header a { color: #888; text-decoration: none; font-size: 0.9rem; }
        .header a:hover { color: #00ffff; }
        .card {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(0, 255, 255, 0.2);
            border-radius: 8px;
            padding: 30px;
            margin-bottom: 20px;
        }
        .card h2 {
            color: #ff6b6b;
            font-size: 1.1rem;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .card p, .card li {
            color: #bbb;
            font-size: 0.9rem;
            line-height: 1.7;
            margin-bottom: 12px;
        }
        .card ul { padding-left: 20px; margin-bottom: 15px; }
        .card li { margin-bottom: 8px; }
        .highlight { color: #ff6b6b; font-weight: 600; }
        .warn { color: #fbbf24; }
        .updated { color: #555; font-size: 0.8rem; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Terms & Disclaimer</h1>
            <a href="/">&larr; Back to Dashboard</a>
        </div>

        <div class="card">
            <h2>Important Legal Disclaimer</h2>
            <p>
                This software is provided <span class="highlight">for educational and entertainment purposes only</span>.
                It is not financial advice. Nothing in this software constitutes a recommendation to buy, sell, or hold
                any cryptocurrency or financial instrument.
            </p>
        </div>

        <div class="card">
            <h2>Use at Your Own Risk</h2>
            <ul>
                <li>This software is <span class="highlight">new and may contain bugs</span> that could result in
                    financial loss. Automated trading carries inherent risks including but not limited to software errors,
                    network failures, and exchange outages.</li>
                <li><span class="warn">Trading is risky and could lead to a complete loss of your funds.</span>
                    Only trade with money you can afford to lose.</li>
                <li><span class="highlight">Always actively monitor your trading positions.</span>
                    Do not rely solely on automated systems to manage your capital.</li>
                <li>You are <span class="highlight">solely responsible</span> for your trading decisions, profits, and losses.
                    The creators of this software accept no liability for any financial losses incurred through its use.</li>
            </ul>
        </div>

        <div class="card">
            <h2>Security</h2>
            <ul>
                <li><span class="highlight">Never expose your private key.</span> Keep your credentials secure and never
                    share them with anyone. Use subaccounts to limit exposure.</li>
                <li>Review all configuration files before running any bot. Understand what each parameter does before
                    deploying with real funds.</li>
            </ul>
        </div>

        <div class="card">
            <h2>Data Accuracy</h2>
            <ul>
                <li>Dashboard numbers, P&L calculations, and equity figures displayed by this software are
                    <span class="highlight">estimates and may not be perfectly accurate</span>.</li>
                <li><span class="warn">Always use the official Hyperliquid UI (app.hyperliquid.xyz) as your
                    source of truth</span> for account balances, positions, and order status.</li>
                <li>In the event of any discrepancy between this dashboard and the exchange UI,
                    the exchange UI should be treated as authoritative.</li>
            </ul>
        </div>

        <div class="card">
            <p>By using this software, you acknowledge that you have read and understood this disclaimer
               and agree to assume all risks associated with its use.</p>
            <p class="updated">Last updated: February 2026</p>
        </div>
    </div>
</body>
</html>
"""


@app.route('/terms')
def terms_page():
    """Terms and disclaimer page"""
    return render_template_string(TERMS_PAGE_TEMPLATE)


# ============================================================================
# DATABASE HELPERS FOR LANDING PAGE
# ============================================================================

def get_pair_stats(pair_name: str) -> dict:
    """Get statistics for a specific pair from database"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as fill_count,
                SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buy_count,
                SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sell_count,
                SUM(quote_amount) as total_volume,
                SUM(fee) as total_fees,
                SUM(realized_pnl) as total_pnl,
                AVG(spread_bps) as avg_spread_captured
            FROM fills
            WHERE pair = ?
        """, (pair_name,))

        row = cursor.fetchone()

        # Get funding for perp markets (table may not exist)
        try:
            cursor.execute("""
                SELECT SUM(payment_usd) as total_funding
                FROM funding_payments
                WHERE market = ?
            """, (pair_name,))
            funding_row = cursor.fetchone()
        except sqlite3.OperationalError:
            funding_row = None

        conn.close()

        if row and row[0] > 0:
            total_pnl = float(row[5] or 0)
            total_fees = float(row[4] or 0)
            total_funding = float(funding_row[0] or 0) if funding_row and funding_row[0] else 0
            net_profit = total_pnl - total_fees + total_funding

            return {
                'fill_count': row[0] or 0,
                'buy_count': row[1] or 0,
                'sell_count': row[2] or 0,
                'total_volume': float(row[3] or 0),
                'total_fees': total_fees,
                'total_pnl': total_pnl,
                'total_funding': total_funding,
                'net_profit': net_profit,
                'avg_spread': float(row[6] or 0)
            }
        else:
            return {
                'fill_count': 0,
                'buy_count': 0,
                'sell_count': 0,
                'total_volume': 0,
                'total_fees': 0,
                'total_pnl': 0,
                'total_funding': 0,
                'net_profit': 0,
                'avg_spread': 0
            }

    except Exception as e:
        print(f"Error getting stats for {pair_name}: {e}")
        return {
            'fill_count': 0,
            'buy_count': 0,
            'sell_count': 0,
            'total_volume': 0,
            'total_fees': 0,
            'total_pnl': 0,
            'total_funding': 0,
            'net_profit': 0,
            'avg_spread': 0,
            'error': str(e)
        }


# ============================================================================
# EMERGENCY STOP PAGE
# ============================================================================

EMERGENCY_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>EMERGENCY STOP - Perp Lobster</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', Monaco, monospace;
            background: #1a0000;
            color: #fff;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            max-width: 500px;
            text-align: center;
        }
        h1 {
            color: #ff4444;
            font-size: 36px;
            margin-bottom: 20px;
        }
        .warning {
            background: #330000;
            border: 2px solid #ff4444;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 30px;
        }
        .warning p {
            color: #ffaaaa;
            margin-bottom: 10px;
        }
        .stop-btn {
            width: 100%;
            padding: 30px;
            font-size: 24px;
            font-weight: bold;
            background: #ff0000;
            color: white;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            margin-bottom: 15px;
            transition: all 0.2s;
        }
        .stop-btn:hover {
            background: #cc0000;
            transform: scale(1.02);
        }
        .stop-btn:disabled {
            background: #666;
            cursor: not-allowed;
            transform: none;
        }
        .status {
            margin-top: 20px;
            padding: 15px;
            border-radius: 8px;
            display: none;
        }
        .status.success {
            display: block;
            background: #003300;
            border: 1px solid #00ff00;
            color: #00ff00;
        }
        .status.error {
            display: block;
            background: #330000;
            border: 1px solid #ff0000;
            color: #ff4444;
        }
        .back-link {
            display: inline-block;
            margin-top: 30px;
            color: #888;
            text-decoration: none;
        }
        .back-link:hover {
            color: #fff;
        }
        .manual-note {
            margin-top: 30px;
            padding: 15px;
            background: #222;
            border-radius: 8px;
            font-size: 12px;
            color: #888;
        }
        .manual-note a {
            color: #00ccff;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>EMERGENCY STOP</h1>

        <div class="warning">
            <p><strong>This will immediately:</strong></p>
            <p>1. Kill all running bot processes</p>
            <p>2. Attempt to cancel all open orders</p>
        </div>

        <button class="stop-btn" id="stopBtn" onclick="emergencyStop()">
            STOP ALL BOTS
        </button>

        <div class="status" id="status"></div>

        <a href="/" class="back-link">← Back to Dashboard</a>

        <div class="manual-note">
            <strong>If this page doesn't work:</strong><br><br>
            Run from terminal:<br>
            <code>python tools/emergency_stop.py</code><br><br>
            Or cancel orders manually:<br>
            <a href="https://app.hyperliquid.xyz/trade" target="_blank">app.hyperliquid.xyz/trade</a>
        </div>
    </div>

    <script>
        async function emergencyStop() {
            const btn = document.getElementById('stopBtn');
            const status = document.getElementById('status');

            btn.disabled = true;
            btn.textContent = 'STOPPING...';
            status.className = 'status';
            status.style.display = 'none';

            try {
                const resp = await fetch('/api/emergency_stop', { method: 'POST' });
                const data = await resp.json();

                if (data.success) {
                    status.className = 'status success';
                    status.innerHTML = '<strong>STOPPED</strong><br>' +
                        'Killed ' + data.processes_killed + ' process(es)<br>' +
                        'Cancelled ' + data.orders_cancelled + ' order(s)';
                    btn.textContent = 'STOPPED';
                    btn.style.background = '#006600';
                } else {
                    throw new Error(data.error || 'Unknown error');
                }
            } catch (err) {
                status.className = 'status error';
                status.innerHTML = '<strong>Error:</strong> ' + err.message +
                    '<br><br>Try running: python tools/emergency_stop.py';
                btn.disabled = false;
                btn.textContent = 'STOP ALL BOTS';
            }
        }
    </script>
</body>
</html>
'''

@app.route('/emergency')
def emergency_page():
    """Emergency stop page - simple failsafe UI"""
    return EMERGENCY_PAGE

@app.route('/api/emergency_stop', methods=['POST'])
def api_emergency_stop():
    """Emergency stop API - kill all bots and cancel orders"""
    import signal
    import subprocess

    results = {
        'success': True,
        'processes_killed': 0,
        'orders_cancelled': 0,
        'errors': []
    }

    # 1. Kill all bot processes via pgrep/kill
    bot_scripts = ['spot_market_maker.py', 'perp_market_maker.py', 'grid_trader.py']
    for script in bot_scripts:
        try:
            result = subprocess.run(['pgrep', '-f', script], capture_output=True, text=True, timeout=5)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        results['processes_killed'] += 1
                    except:
                        pass
        except:
            pass

    # 2. Also stop via bot manager
    try:
        bot_manager = get_bot_manager()
        stop_result = bot_manager.stop_all()
        results['processes_killed'] += stop_result.get('stopped', 0)
    except Exception as e:
        results['errors'].append(f"Bot manager: {str(e)}")

    # 3. Cancel orders on Hyperliquid (main account + all subaccounts)
    try:
        from hyperliquid.info import Info
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
        from eth_account import Account

        creds = get_credentials()
        account_address = creds.get('account_address')
        secret_key = creds.get('secret_key')
        print(f"[Emergency] Main account: {account_address}")

        if not account_address or not secret_key:
            results['errors'].append("Missing credentials - set HL_ACCOUNT_ADDRESS and HL_SECRET_KEY in .env")
            print(f"[Emergency] Missing credentials!")
            return jsonify(results)

        # Create wallet from secret key
        if not secret_key.startswith('0x'):
            secret_key = '0x' + secret_key
        wallet = Account.from_key(secret_key)
        print(f"[Emergency] Wallet created: {wallet.address}")

        # Initialize with perp_dexs for HIP-3 builder markets (xyz, flx, etc.)
        # Without this, orders on builder markets won't be visible
        info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=["", "xyz", "flx"])

        # Collect all addresses and their associated dexes to check
        # Format: [(address, dex_list), ...]
        addresses_to_check = [(account_address, [""])]  # Main account, main dex

        # Find subaccounts and their dexes from config files
        dexes_found = set([""])  # Always check main dex
        for filename in os.listdir(CONFIG_DIR):
            if filename.endswith('.json') and filename != 'config.json':
                try:
                    with open(os.path.join(CONFIG_DIR, filename), 'r') as f:
                        cfg = json.load(f)
                    sub_addr = cfg.get('account', {}).get('subaccount_address')
                    dex = cfg.get('dex', '')  # HIP-3 dex like "xyz", "flx"
                    if dex:
                        dexes_found.add(dex)
                        print(f"[Emergency] Found dex '{dex}' in config")
                    if sub_addr:
                        # Check if this subaccount is already in our list
                        existing = [a for a, d in addresses_to_check if a == sub_addr]
                        if not existing:
                            addresses_to_check.append((sub_addr, list(dexes_found)))
                            print(f"[Emergency] Found subaccount: {sub_addr}")
                except:
                    pass

        # Update all addresses to check all found dexes
        addresses_to_check = [(addr, list(dexes_found)) for addr, _ in addresses_to_check]
        print(f"[Emergency] Checking {len(addresses_to_check)} addresses with dexes: {list(dexes_found)}")

        # Cancel orders for each address and dex combination
        for addr, dex_list in addresses_to_check:
            for dex in dex_list:
                try:
                    dex_label = f"dex='{dex}'" if dex else "main"
                    print(f"[Emergency] Querying open orders for {addr[:10]}... ({dex_label})")

                    # Query with dex parameter for HIP-3 markets
                    if dex:
                        open_orders = info.open_orders(addr, dex=dex)
                    else:
                        open_orders = info.open_orders(addr)

                    print(f"[Emergency] Found {len(open_orders) if open_orders else 0} open orders for {addr[:10]}... ({dex_label})")

                    # Also check user state to see positions/account info
                    try:
                        if dex:
                            user_state = info.user_state(addr, dex=dex)
                        else:
                            user_state = info.user_state(addr)
                        if user_state:
                            positions = user_state.get('assetPositions', [])
                            active_positions = [p for p in positions if p.get('position', {}).get('szi', '0') != '0']
                            if active_positions:
                                print(f"[Emergency] User state for {addr[:10]}... ({dex_label}): {len(active_positions)} active positions")
                                for pos in active_positions:
                                    print(f"[Emergency]   Position: {pos.get('position', {})}")
                    except Exception as e:
                        print(f"[Emergency] Could not get user state: {e}")

                    if open_orders:
                        # Create exchange with vault_address for subaccounts
                        # Include perp_dexs for HIP-3 builder markets
                        vault = addr if addr != account_address else None
                        exchange = Exchange(wallet, constants.MAINNET_API_URL, vault_address=vault, perp_dexs=["", "xyz", "flx"])

                        for order in open_orders:
                            try:
                                coin = order.get('coin')
                                oid = order.get('oid')
                                print(f"[Emergency] Cancelling {coin} order {oid}...")
                                cancel_result = exchange.cancel(coin, oid)
                                print(f"[Emergency] Cancel result: {cancel_result}")
                                if cancel_result.get('status') == 'ok':
                                    results['orders_cancelled'] += 1
                            except Exception as e:
                                print(f"[Emergency] Cancel error: {e}")
                                results['errors'].append(f"Cancel {order.get('coin')}: {str(e)}")
                except Exception as e:
                    print(f"[Emergency] Error checking {addr[:10]}... ({dex_label}): {e}")
                    results['errors'].append(f"Check orders for {addr[:10]}...: {str(e)}")

    except ImportError:
        results['errors'].append("Hyperliquid SDK not installed")
    except Exception as e:
        results['errors'].append(f"Order cancellation: {str(e)}")

    return jsonify(results)


@app.route('/api/stop_all', methods=['POST'])
def api_stop_all():
    """Stop all bots and cancel all orders - called from Stop All button"""
    print("[StopAll] Stop all bots requested")
    return api_emergency_stop()

# ============================================================================
# ACCOUNTS MANAGEMENT
# ============================================================================

from credentials import get_accounts, save_accounts, get_all_addresses, discover_subaccounts

@app.route('/accounts')
def accounts_page():
    """Account registry management page"""
    return render_template_string(ACCOUNTS_PAGE_TEMPLATE)

@app.route('/api/accounts', methods=['GET'])
def api_get_accounts():
    """Get current account registry"""
    accounts = get_accounts()
    return jsonify(accounts)

@app.route('/api/accounts', methods=['POST'])
def api_save_accounts():
    """Save account registry"""
    data = request.json
    save_accounts(data)
    return jsonify({'success': True})

@app.route('/api/accounts/discover', methods=['POST'])
def api_discover_subaccounts():
    """Auto-discover subaccounts from Hyperliquid API"""
    data = request.json or {}
    address = data.get('address')
    try:
        result = discover_subaccounts(address)
        if 'error' in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/accounts/balances', methods=['GET'])
def api_accounts_balances():
    """Fetch live perps + spot equity for all accounts using HL portfolio endpoint"""
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        all_addrs = get_all_addresses()
        results = []

        for entry in all_addrs:
            addr = entry['address']
            label = entry['label']
            perp_equity = 0.0
            spot_equity = 0.0

            try:
                # Portfolio endpoint returns both total and perp-only equity
                # (same values the Hyperliquid UI displays)
                portfolio = info.post('/info', {'type': 'portfolio', 'user': addr})
                total_equity = 0.0
                for period_data in portfolio:
                    period = period_data[0]
                    if period == 'allTime':
                        hist = period_data[1].get('accountValueHistory', [])
                        if hist:
                            total_equity = float(hist[-1][1])
                    elif period == 'perpAllTime':
                        hist = period_data[1].get('accountValueHistory', [])
                        if hist:
                            perp_equity = float(hist[-1][1])
                spot_equity = total_equity - perp_equity
            except Exception:
                pass

            results.append({
                'address': addr,
                'label': label,
                'perp_equity': round(perp_equity, 2),
                'spot_equity': round(spot_equity, 2)
            })

        return jsonify({'accounts': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

ACCOUNTS_PAGE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Accounts - Perp Lobster</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Fira Code', monospace;
            background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #0f0f1a 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 30px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        .header { margin-bottom: 30px; }
        .header h1 { color: #00ffff; margin-bottom: 8px; font-size: 1.5rem; }
        .header a { color: #888; text-decoration: none; font-size: 0.9rem; }
        .header a:hover { color: #00ffff; }

        .card {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(0, 255, 255, 0.2);
            border-radius: 8px;
            padding: 25px;
            margin-bottom: 20px;
        }
        .card h2 { color: #00ffff; font-size: 1.1rem; margin-bottom: 15px; }

        .main-account-row {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .main-account-row input {
            flex: 1;
            padding: 12px;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(0, 255, 255, 0.3);
            border-radius: 6px;
            color: #e0e0e0;
            font-family: inherit;
            font-size: 0.9rem;
        }
        .main-account-row input:focus { outline: none; border-color: #00ffff; }

        .btn {
            padding: 12px 20px;
            border: none;
            border-radius: 6px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.85rem;
            transition: all 0.2s;
            white-space: nowrap;
        }
        .btn-primary { background: linear-gradient(135deg, #00aaaa, #008888); }
        .btn-primary:hover { background: linear-gradient(135deg, #00cccc, #00aaaa); }
        .btn-accent { background: linear-gradient(135deg, #6366f1, #8b5cf6); }
        .btn-accent:hover { background: linear-gradient(135deg, #7c7cf9, #9d6eef); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }

        .accounts-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        .accounts-table th {
            text-align: left;
            color: #888;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            padding: 10px 12px;
            border-bottom: 1px solid rgba(0, 255, 255, 0.15);
        }
        .accounts-table th.right { text-align: right; }
        .accounts-table td {
            padding: 12px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.9rem;
        }
        .accounts-table tr:hover { background: rgba(0, 255, 255, 0.03); }
        .accounts-table tr.main-row { background: rgba(0, 255, 255, 0.04); }
        .accounts-table tr.main-row td { border-bottom: 1px solid rgba(0, 255, 255, 0.12); }

        .addr-cell {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .addr-text {
            color: #a5b4fc;
            font-size: 0.85rem;
            font-family: 'SF Mono', 'Fira Code', monospace;
        }
        .copy-btn {
            background: none;
            border: none;
            color: #555;
            cursor: pointer;
            padding: 4px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            transition: all 0.2s;
        }
        .copy-btn:hover { color: #00ffff; background: rgba(0, 255, 255, 0.1); }
        .copy-btn.copied { color: #4ade80; }
        .copy-btn svg { width: 14px; height: 14px; }

        .label-text { color: #e0e0e0; }
        .label-badge {
            display: inline-block;
            font-size: 0.65rem;
            padding: 2px 6px;
            border-radius: 3px;
            margin-left: 8px;
            vertical-align: middle;
        }
        .label-badge.main {
            background: rgba(0, 255, 255, 0.15);
            color: #00ffff;
            border: 1px solid rgba(0, 255, 255, 0.3);
        }

        .equity { text-align: right; font-variant-numeric: tabular-nums; }
        .equity-val { color: #4ade80; }
        .equity-val.zero { color: #555; }
        .equity-loading { color: #555; font-size: 0.8rem; }

        .total-row td {
            border-top: 1px solid rgba(0, 255, 255, 0.2);
            border-bottom: none;
            font-weight: 600;
            padding-top: 14px;
        }
        .total-label { color: #888; text-transform: uppercase; font-size: 0.8rem; }
        .total-val { color: #00ffff; }

        .status-msg {
            padding: 12px;
            border-radius: 6px;
            margin-top: 15px;
            font-size: 0.9rem;
        }
        .status-msg.success { background: rgba(0, 200, 0, 0.15); border: 1px solid rgba(0, 200, 0, 0.25); color: #4ade80; }
        .status-msg.error { background: rgba(200, 50, 50, 0.15); border: 1px solid rgba(200, 50, 50, 0.25); color: #f87171; }
        .status-msg.info { background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.25); color: #a5b4fc; }

        .empty-state {
            text-align: center;
            color: #555;
            padding: 30px;
            font-size: 0.95rem;
        }
        .synced-at { color: #555; font-size: 0.8rem; margin-top: 10px; }

        .loading-spinner {
            display: inline-block;
            width: 14px; height: 14px;
            border: 2px solid rgba(0, 255, 255, 0.3);
            border-top-color: #00ffff;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
            vertical-align: middle;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        .tooltip {
            position: fixed;
            background: #1a1a2e;
            color: #4ade80;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 0.75rem;
            border: 1px solid rgba(74, 222, 128, 0.3);
            pointer-events: none;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.2s;
        }
        .tooltip.show { opacity: 1; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Accounts</h1>
            <a href="/">&larr; Back to Dashboard</a>
        </div>

        <div class="card">
            <h2>Main Wallet</h2>
            <p style="color: #888; font-size: 0.85rem; margin-bottom: 12px;">
                Enter your Hyperliquid wallet address and click Sync to auto-discover all subaccounts.
            </p>
            <div class="main-account-row">
                <input type="text" id="mainAddress" placeholder="0x..." spellcheck="false">
                <button class="btn btn-accent" id="syncBtn" onclick="syncAccounts()">Sync Subaccounts</button>
            </div>
            <div id="syncStatus"></div>
        </div>

        <div class="card">
            <h2>All Accounts</h2>
            <div id="accountsList">
                <div class="empty-state">Loading...</div>
            </div>
            <div id="syncedAt" class="synced-at"></div>
        </div>
    </div>

    <div class="tooltip" id="copyTooltip">Copied!</div>

    <script>
        const COPY_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path></svg>';
        const CHECK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';

        let currentAccounts = {};

        function formatUsd(val) {
            if (val === null || val === undefined) return '<span class="equity-loading">--</span>';
            const num = parseFloat(val);
            if (num === 0) return '<span class="equity-val zero">$0.00</span>';
            return '<span class="equity-val">$' + num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</span>';
        }

        function truncAddr(addr) {
            return addr.slice(0, 6) + '...' + addr.slice(-4);
        }

        async function copyAddress(addr, btnEl, evt) {
            try {
                await navigator.clipboard.writeText(addr);
                btnEl.innerHTML = CHECK_ICON;
                btnEl.classList.add('copied');

                const tooltip = document.getElementById('copyTooltip');
                tooltip.style.left = (evt.clientX + 10) + 'px';
                tooltip.style.top = (evt.clientY - 30) + 'px';
                tooltip.classList.add('show');

                setTimeout(() => {
                    btnEl.innerHTML = COPY_ICON;
                    btnEl.classList.remove('copied');
                    tooltip.classList.remove('show');
                }, 1500);
            } catch (e) {
                console.error('Copy failed:', e);
            }
        }

        function buildTable(accounts, balances) {
            const balMap = {};
            if (balances) {
                for (const b of balances) {
                    balMap[b.address.toLowerCase()] = b;
                }
            }

            let html = '<table class="accounts-table"><thead><tr>';
            html += '<th>Label</th>';
            html += '<th>Address</th>';
            html += '<th class="right">Perps Equity</th>';
            html += '<th class="right">Spot Equity</th>';
            html += '</tr></thead><tbody>';

            let totalPerp = 0, totalSpot = 0;

            // Main account first
            const main = accounts.main_account;
            if (main) {
                const bal = balMap[main.toLowerCase()];
                const perpVal = bal ? bal.perp_equity : null;
                const spotVal = bal ? bal.spot_equity : null;
                if (perpVal !== null) totalPerp += perpVal;
                if (spotVal !== null) totalSpot += spotVal;

                html += '<tr class="main-row">';
                html += '<td class="label-text">Main Account<span class="label-badge main">MAIN</span></td>';
                html += '<td><div class="addr-cell"><span class="addr-text" title="' + main + '">' + truncAddr(main) + '</span>';
                html += '<button class="copy-btn" onclick="copyAddress(\\\'' + main + '\\\', this, event)" title="Copy address">' + COPY_ICON + '</button>';
                html += '</div></td>';
                html += '<td class="equity">' + formatUsd(perpVal) + '</td>';
                html += '<td class="equity">' + formatUsd(spotVal) + '</td>';
                html += '</tr>';
            }

            // Subaccounts
            const subs = accounts.subaccounts || [];
            for (const sub of subs) {
                const addr = sub.address;
                const bal = balMap[addr.toLowerCase()];
                const perpVal = bal ? bal.perp_equity : null;
                const spotVal = bal ? bal.spot_equity : null;
                if (perpVal !== null) totalPerp += perpVal;
                if (spotVal !== null) totalSpot += spotVal;

                html += '<tr>';
                html += '<td class="label-text">' + (sub.label || 'Unnamed') + '</td>';
                html += '<td><div class="addr-cell"><span class="addr-text" title="' + addr + '">' + truncAddr(addr) + '</span>';
                html += '<button class="copy-btn" onclick="copyAddress(\\\'' + addr + '\\\', this, event)" title="Copy address">' + COPY_ICON + '</button>';
                html += '</div></td>';
                html += '<td class="equity">' + formatUsd(perpVal) + '</td>';
                html += '<td class="equity">' + formatUsd(spotVal) + '</td>';
                html += '</tr>';
            }

            // Totals row
            html += '<tr class="total-row">';
            html += '<td class="total-label">Total</td>';
            html += '<td></td>';
            html += '<td class="equity"><span class="total-val">$' + totalPerp.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</span></td>';
            html += '<td class="equity"><span class="total-val">$' + totalSpot.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</span></td>';
            html += '</tr>';

            html += '</tbody></table>';
            return html;
        }

        async function loadAccounts() {
            try {
                const resp = await fetch('/api/accounts');
                currentAccounts = await resp.json();

                document.getElementById('mainAddress').value = currentAccounts.main_account || '';

                const main = currentAccounts.main_account;
                const subs = currentAccounts.subaccounts || [];

                const container = document.getElementById('accountsList');

                if (!main && subs.length === 0) {
                    container.innerHTML = '<div class="empty-state">No accounts found. Enter your wallet address above and click Sync.</div>';
                    return;
                }

                // Render table with loading placeholders for balances
                container.innerHTML = buildTable(currentAccounts, null);

                // Fetch live balances
                fetchBalances();

                if (currentAccounts.last_synced) {
                    const d = new Date(currentAccounts.last_synced);
                    document.getElementById('syncedAt').textContent = 'Last synced: ' + d.toLocaleString();
                }
            } catch (e) {
                document.getElementById('accountsList').innerHTML =
                    '<div class="status-msg error">Failed to load accounts: ' + e.message + '</div>';
            }
        }

        async function fetchBalances() {
            try {
                const resp = await fetch('/api/accounts/balances');
                const data = await resp.json();
                if (data.accounts) {
                    const container = document.getElementById('accountsList');
                    container.innerHTML = buildTable(currentAccounts, data.accounts);
                }
            } catch (e) {
                console.error('Failed to fetch balances:', e);
            }
        }

        async function syncAccounts() {
            const address = document.getElementById('mainAddress').value.trim();
            if (!address || !address.startsWith('0x')) {
                document.getElementById('syncStatus').innerHTML =
                    '<div class="status-msg error">Enter a valid wallet address starting with 0x</div>';
                return;
            }

            const btn = document.getElementById('syncBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="loading-spinner"></span>Syncing...';
            document.getElementById('syncStatus').innerHTML =
                '<div class="status-msg info"><span class="loading-spinner"></span>Querying Hyperliquid for subaccounts...</div>';

            try {
                const resp = await fetch('/api/accounts/discover', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ address: address })
                });
                const data = await resp.json();

                if (data.error) {
                    document.getElementById('syncStatus').innerHTML =
                        '<div class="status-msg error">' + data.error + '</div>';
                } else {
                    const count = (data.subaccounts || []).length;
                    document.getElementById('syncStatus').innerHTML =
                        '<div class="status-msg success">Found ' + count + ' subaccount' + (count !== 1 ? 's' : '') + '!</div>';
                    loadAccounts();
                }
            } catch (e) {
                document.getElementById('syncStatus').innerHTML =
                    '<div class="status-msg error">Sync failed: ' + e.message + '</div>';
            } finally {
                btn.disabled = false;
                btn.innerHTML = 'Sync Subaccounts';
            }
        }

        loadAccounts();
    </script>
</body>
</html>
'''


# ============================================================================
# LANDING PAGE
# ============================================================================

@app.route('/')
def index():
    """Landing page with all pairs overview"""
    return render_template_string(LANDING_PAGE_TEMPLATE, pairs=ALL_PAIRS)


@app.route('/api/overview')
def api_overview():
    """Get overview stats for all pairs"""
    overview = []

    for pair_info in ALL_PAIRS:
        # Database stores "BTC-PERP" format for perps
        if pair_info['type'] == 'perp':
            db_name = f"{pair_info.get('market_name', pair_info['base_token'])}-PERP"
        else:
            db_name = pair_info['pair']
        stats = get_pair_stats(db_name)
        overview.append({
            'pair': pair_info['pair'],
            'type': pair_info['type'],
            'route': pair_info['route'],
            'stats': stats
        })

    # Calculate totals
    total_pnl = sum(p['stats'].get('total_pnl', 0) for p in overview)
    total_fees = sum(p['stats'].get('total_fees', 0) for p in overview)
    total_funding = sum(p['stats'].get('total_funding', 0) for p in overview)
    total_volume = sum(p['stats'].get('total_volume', 0) for p in overview)
    total_fills = sum(p['stats'].get('fill_count', 0) for p in overview)

    return jsonify({
        'pairs': overview,
        'totals': {
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'total_funding': total_funding,
            'net_profit': total_pnl - total_fees + total_funding,
            'total_volume': total_volume,
            'total_fills': total_fills
        }
    })


# ============================================================================
# LANDING PAGE TEMPLATE
# ============================================================================

LANDING_PAGE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Perp Lobster Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            background: #0a0e27;
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 40px 30px;
            background: linear-gradient(135deg, #1a1f3a 0%, #2a2f4a 100%);
            border-radius: 12px;
            margin-bottom: 30px;
            border: 1px solid #00ccff;
        }
        .header > div { text-align: left; }
        .config-btn {
            padding: 12px 24px;
            background: #00ccff;
            color: #0a0e27;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.2s;
        }
        .config-btn:hover {
            background: #00a3cc;
            transform: translateY(-2px);
        }
        .settings-btn {
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(99, 102, 241, 0.2);
            border: 1px solid rgba(99, 102, 241, 0.4);
            border-radius: 8px;
            text-decoration: none;
            font-size: 18px;
            transition: all 0.2s;
        }
        .settings-btn:hover {
            background: rgba(99, 102, 241, 0.4);
            transform: translateY(-2px);
        }
        .header-buttons {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .stop-all-btn {
            padding: 12px 24px;
            background: #ef4444;
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.2s;
        }
        .stop-all-btn:hover {
            background: #dc2626;
            transform: translateY(-2px);
        }
        h1 {
            font-size: 36px;
            font-weight: 600;
            margin-bottom: 10px;
            color: #00ccff;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        .subtitle { color: #8b92b0; font-size: 14px; }

        /* Totals Section */
        .totals-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .total-card {
            background: #1a1f3a;
            padding: 20px;
            border-radius: 8px;
            border-left: 3px solid #00ccff;
            text-align: center;
        }
        .total-label {
            font-size: 11px;
            color: #8b92b0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .total-value {
            font-size: 28px;
            font-weight: 600;
        }

        /* Pairs Grid */
        .section-title {
            font-size: 18px;
            color: #00ccff;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #2a2f4a;
        }
        .pairs-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 20px;
        }
        .pair-card {
            background: #1a1f3a;
            border-radius: 12px;
            padding: 25px;
            border: 1px solid #2a2f4a;
            cursor: pointer;
            transition: all 0.2s;
        }
        .pair-card:hover {
            border-color: #00ccff;
            transform: translateY(-3px);
            box-shadow: 0 10px 30px rgba(0, 204, 255, 0.1);
        }
        .pair-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .pair-name {
            font-size: 22px;
            font-weight: 600;
            color: #fff;
        }
        .pair-type {
            background: #667eea;
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .pair-type.perp { background: #f59e0b; }
        .pair-type.spot { background: #10b981; }

        .pair-stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }
        .stat {
            background: #0a0e27;
            padding: 12px;
            border-radius: 6px;
        }
        .stat-label {
            font-size: 10px;
            color: #8b92b0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        .stat-value {
            font-size: 18px;
            font-weight: 600;
        }

        .positive { color: #4ade80; }
        .negative { color: #f87171; }
        .neutral { color: #60a5fa; }

        .no-data {
            text-align: center;
            padding: 60px;
            color: #8b92b0;
            grid-column: 1 / -1;
        }
        .no-data h2 { margin-bottom: 15px; color: #00ccff; }

        .loading {
            text-align: center;
            padding: 40px;
            color: #8b92b0;
        }

        @media (max-width: 768px) {
            .totals-grid { grid-template-columns: repeat(2, 1fr); }
            .pairs-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>Perp Lobster</h1>
                <p class="subtitle">Unified Trading Dashboard</p>
            </div>
            <div class="header-buttons">
                <button class="stop-all-btn" onclick="stopAllBots()">Stop All</button>
                <a href="/ai" class="settings-btn" title="AI Settings">⚙️</a>
                <a href="/accounts" class="config-btn">Accounts</a>
                <a href="/config" class="config-btn">Config Manager</a>
            </div>
        </div>

        <!-- Portfolio Totals -->
        <div class="totals-grid" id="totals-grid">
            <div class="total-card">
                <div class="total-label">Net Profit</div>
                <div class="total-value" id="total-net">--</div>
            </div>
            <div class="total-card">
                <div class="total-label">Total PnL</div>
                <div class="total-value" id="total-pnl">--</div>
            </div>
            <div class="total-card">
                <div class="total-label">Total Fees</div>
                <div class="total-value negative" id="total-fees">--</div>
            </div>
            <div class="total-card">
                <div class="total-label">Total Volume</div>
                <div class="total-value neutral" id="total-volume">--</div>
            </div>
            <div class="total-card">
                <div class="total-label">Total Fills</div>
                <div class="total-value neutral" id="total-fills">--</div>
            </div>
        </div>

        <!-- Trading Pairs -->
        <div class="section-title">Trading Pairs</div>
        <div class="pairs-grid" id="pairs-grid">
            <div class="loading">Loading trading pairs...</div>
        </div>
    </div>

    <script>
        async function loadOverview() {
            try {
                const resp = await fetch('/api/overview');
                const data = await resp.json();

                // Update totals
                const t = data.totals;
                document.getElementById('total-net').textContent = '$' + t.net_profit.toFixed(2);
                document.getElementById('total-net').className = 'total-value ' + (t.net_profit >= 0 ? 'positive' : 'negative');

                document.getElementById('total-pnl').textContent = '$' + t.total_pnl.toFixed(2);
                document.getElementById('total-pnl').className = 'total-value ' + (t.total_pnl >= 0 ? 'positive' : 'negative');

                document.getElementById('total-fees').textContent = '$' + t.total_fees.toFixed(2);
                document.getElementById('total-volume').textContent = '$' + t.total_volume.toFixed(0);
                document.getElementById('total-fills').textContent = t.total_fills;

                // Update pairs grid
                const grid = document.getElementById('pairs-grid');

                if (!data.pairs || data.pairs.length === 0) {
                    grid.innerHTML = `
                        <div class="no-data">
                            <h2>No Trading Pairs Found</h2>
                            <p>Add config files to the config/ directory to get started.</p>
                            <p style="margin-top: 10px; font-size: 12px;">
                                Copy from config/examples/ and customize for your markets.
                            </p>
                        </div>
                    `;
                    return;
                }

                grid.innerHTML = data.pairs.map(p => {
                    const s = p.stats;
                    const netClass = s.net_profit >= 0 ? 'positive' : 'negative';
                    const typeClass = p.type;

                    return `
                        <div class="pair-card" onclick="window.location='/${p.route}'">
                            <div class="pair-header">
                                <div class="pair-name">${p.pair}</div>
                                <div class="pair-type ${typeClass}">${p.type}</div>
                            </div>
                            <div class="pair-stats">
                                <div class="stat">
                                    <div class="stat-label">Net Profit</div>
                                    <div class="stat-value ${netClass}">$${s.net_profit.toFixed(2)}</div>
                                </div>
                                <div class="stat">
                                    <div class="stat-label">Fills</div>
                                    <div class="stat-value neutral">${s.fill_count}</div>
                                </div>
                                <div class="stat">
                                    <div class="stat-label">Volume</div>
                                    <div class="stat-value neutral">$${s.total_volume.toFixed(0)}</div>
                                </div>
                                <div class="stat">
                                    <div class="stat-label">Avg Spread</div>
                                    <div class="stat-value neutral">${s.avg_spread.toFixed(1)} bps</div>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');

            } catch (err) {
                console.error('Error loading overview:', err);
                document.getElementById('pairs-grid').innerHTML = `
                    <div class="no-data">
                        <h2>Error Loading Data</h2>
                        <p>${err.message}</p>
                    </div>
                `;
            }
        }

        // Initial load
        loadOverview();

        // Refresh every 30 seconds
        setInterval(loadOverview, 30000);

        // Stop All Bots function - kills bots AND cancels all orders
        async function stopAllBots() {
            if (!confirm('Stop all bots and cancel all open orders?')) return;
            try {
                const resp = await fetch('/api/stop_all', { method: 'POST' });
                const data = await resp.json();
                let msg = 'Stopped ' + data.processes_killed + ' bot(s)';
                msg += '\\nCancelled ' + data.orders_cancelled + ' order(s)';
                if (data.errors && data.errors.length > 0) {
                    msg += '\\n\\nWarnings: ' + data.errors.join(', ');
                }
                alert(msg);
            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

    </script>
    <!-- Footer + AI Chat injected automatically by after_request -->
</body>
</html>
'''


# ============================================================================
# WEBSOCKET EVENT HANDLERS
# ============================================================================

if SOCKETIO_AVAILABLE:
    # Set up bot manager with log streaming callback
    try:
        bot_manager = get_bot_manager(bots_dir=BOTS_DIR, config_dir=CONFIG_DIR)

        def on_log_line(config_file, log_line):
            """Called when a bot produces a log line - stream to connected clients"""
            socketio.emit('bot_log', {
                'config_file': config_file,
                'line': log_line
            })

        def on_status_change(config_file, status, full_status):
            """Called when bot status changes - use background task to avoid blocking"""
            print(f"[Dashboard] on_status_change called: {config_file} -> {status}", flush=True)
            try:
                # Use start_background_task to avoid blocking in non-eventlet threads
                def emit_status():
                    socketio.emit('bot_status', {
                        'config_file': config_file,
                        'status': status,
                        'data': full_status
                    })
                    print(f"[Dashboard] socketio.emit completed", flush=True)
                socketio.start_background_task(emit_status)
            except Exception as e:
                print(f"[Dashboard] socketio.emit error: {e}", flush=True)

        bot_manager.set_log_callback(on_log_line)
        bot_manager.set_status_callback(on_status_change)
        print(f"[Dashboard] Set callbacks on bot_manager instance: {id(bot_manager)}")

    except Exception as e:
        print(f"Warning: Could not initialize bot manager for WebSocket: {e}")

    @socketio.on('connect')
    def handle_connect():
        print('[WebSocket] Client connected')
        emit('connected', {'status': 'ok'})

    @socketio.on('disconnect')
    def handle_disconnect():
        print('[WebSocket] Client disconnected')

    @socketio.on('subscribe_logs')
    def handle_subscribe_logs(data):
        """Client wants to subscribe to logs for a specific bot"""
        config_file = data.get('config_file')
        print(f'[WebSocket] Client subscribed to logs for {config_file}')
        # Send recent log history
        try:
            bot_manager = get_bot_manager()
            logs = bot_manager.get_logs(config_file, n=100)
            emit('log_history', {
                'config_file': config_file,
                'logs': logs.get('logs', [])
            })
        except Exception as e:
            emit('error', {'message': str(e)})

    @socketio.on('get_all_status')
    def handle_get_all_status():
        """Client requests current status of all bots"""
        try:
            bot_manager = get_bot_manager()
            statuses = bot_manager.get_all_status()
            emit('all_status', {'bots': statuses})
        except Exception as e:
            emit('error', {'message': str(e)})


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    if SOCKETIO_AVAILABLE:
        print("Starting with WebSocket support (real-time logs enabled)")
        # Note: debug=True with use_reloader=False for eventlet compatibility
        # The reloader doesn't work well with eventlet monkey patching
        socketio.run(app, host='0.0.0.0', port=5050, debug=True, use_reloader=False, log_output=True)
    else:
        print("Starting without WebSocket support (install flask-socketio for real-time logs)")
        app.run(host='0.0.0.0', port=5050, debug=True)
