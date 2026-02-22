"""
Credentials loader
Loads account credentials and AI settings from .env file,
falling back to config.json / .ai_settings.json for backwards compatibility.
"""

import json
import os
import sqlite3
import glob
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_PROJECT_ROOT, '.env')
load_dotenv(_ENV_PATH)


def get_credentials() -> dict:
    """
    Get Hyperliquid account credentials.
    Priority: .env > config.json

    Returns:
        dict with 'account_address' and 'secret_key'
    """
    account_address = os.environ.get('HL_ACCOUNT_ADDRESS')
    secret_key = os.environ.get('HL_SECRET_KEY')

    if account_address and secret_key:
        return {
            'account_address': account_address,
            'secret_key': secret_key
        }

    # Fallback to config.json
    config_path = os.path.join(_PROJECT_ROOT, 'config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
        return {
            'account_address': config.get('account_address', ''),
            'secret_key': config.get('secret_key', '')
        }

    return {'account_address': '', 'secret_key': ''}


def get_ai_settings() -> dict:
    """
    Get AI assistant settings.
    Priority: .env > .ai_settings.json

    Returns:
        dict with 'anthropic_api_key' and 'model'
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    model = os.environ.get('AI_MODEL')

    # Load file settings as base (may have other fields)
    settings_path = os.path.join(_PROJECT_ROOT, '.ai_settings.json')
    file_settings = {}
    if os.path.exists(settings_path):
        with open(settings_path, 'r') as f:
            file_settings = json.load(f)

    # Env vars override file values
    if api_key:
        file_settings['anthropic_api_key'] = api_key
    if model:
        file_settings['model'] = model

    # Defaults
    file_settings.setdefault('model', 'claude-sonnet-4-20250514')

    return file_settings


# ============================================================================
# Builder Fee Configuration
# ============================================================================
# Builder fees support ongoing development of Perp Lobster.
# 1 bps (0.01%) is added to each trade. The fee parameter 'f' is in tenths
# of a basis point, so f=10 equals 1 bps.

BUILDER_ADDRESS = "0xC8f0cD137E28f717A20f810b46926f92978BbCfA"
BUILDER_FEE = 10  # tenths of bps (10 = 1 bps = 0.01%)


def get_builder():
    """Get builder fee config for order placement.
    Returns dict with 'b' (address) and 'f' (fee in tenths of bps).
    """
    return {"b": BUILDER_ADDRESS, "f": BUILDER_FEE}


def ensure_builder_fee_approved(exchange):
    """Auto-approve builder fee on first run. Called during bot startup.
    Uses the exchange's wallet to sign the approval transaction.
    This is a one-time operation — subsequent calls are no-ops on Hyperliquid's side.

    Note: Builder fee approval is a "user-signed" action on Hyperliquid, which means
    it must be signed by the main wallet — API/agent wallets cannot approve builder fees.
    If using an API wallet, approve the builder fee once from the main wallet first.
    """
    # Skip if using an API wallet (account_address differs from wallet address)
    is_api_wallet = (
        exchange.account_address is not None
        and exchange.account_address != ""
        and exchange.account_address.lower() != exchange.wallet.address.lower()
    )
    if is_api_wallet:
        return  # API wallets can't approve — must be done from main wallet

    try:
        max_fee_rate = f"{BUILDER_FEE / 1000:.4f}%"
        result = exchange.approve_builder_fee(BUILDER_ADDRESS, max_fee_rate)
        if result.get("status") == "ok":
            print(f"   Builder fee approved ({max_fee_rate} per trade)")
    except Exception as e:
        error_msg = str(e)
        if "already" in error_msg.lower():
            pass  # Already approved — nothing to do
        else:
            print(f"   Builder fee note: {error_msg}")
            print(f"   (Orders may fail if fee not approved from main wallet)")


# ============================================================================
# Account Registry (accounts.json)
# ============================================================================

_ACCOUNTS_PATH = os.path.join(_PROJECT_ROOT, 'accounts.json')


def get_accounts() -> dict:
    """
    Get the account registry.
    Returns dict with 'main_account' and 'subaccounts' list.
    Falls back to .env main address if accounts.json doesn't exist.
    """
    if os.path.exists(_ACCOUNTS_PATH):
        with open(_ACCOUNTS_PATH, 'r') as f:
            return json.load(f)

    # Bootstrap from .env / config.json
    creds = get_credentials()
    return {
        'main_account': creds.get('account_address', ''),
        'subaccounts': [],
        'last_synced': None
    }


def save_accounts(accounts: dict):
    """Save account registry to accounts.json"""
    with open(_ACCOUNTS_PATH, 'w') as f:
        json.dump(accounts, f, indent=2)


def get_all_addresses() -> list:
    """
    Get main account + all subaccount addresses with labels.
    Single source of truth used by AI assistant, dashboard, etc.

    Returns:
        list of {'address': '0x...', 'label': 'Name'}
    """
    accounts = get_accounts()
    result = []

    main = accounts.get('main_account', '')
    if main:
        result.append({'address': main, 'label': 'Main Account'})

    for sub in accounts.get('subaccounts', []):
        addr = sub.get('address', '')
        if addr and addr != main:
            result.append({'address': addr, 'label': sub.get('label', 'Subaccount')})

    return result


def discover_subaccounts(main_address: str = None) -> dict:
    """
    Query Hyperliquid API to discover all subaccounts for a main address.
    Updates accounts.json with results.

    Args:
        main_address: Main wallet address. If None, reads from current config.

    Returns:
        Updated accounts dict
    """
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    from datetime import datetime, timezone

    if not main_address:
        main_address = get_accounts().get('main_account') or get_credentials().get('account_address')

    if not main_address:
        return {'error': 'No main account address configured. Set HL_ACCOUNT_ADDRESS in .env'}

    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    raw = info.post('/info', {'type': 'subAccounts', 'user': main_address})

    subaccounts = []
    for sub in raw:
        subaccounts.append({
            'address': sub['subAccountUser'],
            'label': sub.get('name', 'Unnamed')
        })

    accounts = {
        'main_account': main_address,
        'subaccounts': subaccounts,
        'last_synced': datetime.now(timezone.utc).isoformat()
    }

    save_accounts(accounts)
    return accounts


# ============================================================================
# Setup Helpers (used by dashboard setup wizard)
# ============================================================================

_PLACEHOLDER_VALUES = {
    '0xYourWalletAddress',
    'your_private_key_hex_without_0x_prefix',
    '',
}


def needs_setup() -> bool:
    """Check if credentials need to be configured.
    Returns True if .env has placeholder values or is missing credentials.
    """
    creds = get_credentials()
    address = creds.get('account_address', '')
    key = creds.get('secret_key', '')
    return address in _PLACEHOLDER_VALUES or key in _PLACEHOLDER_VALUES


def write_credentials_to_env(account_address: str, secret_key: str):
    """Write Hyperliquid credentials to the .env file.
    Preserves all existing lines (comments, ANTHROPIC_API_KEY, etc.).
    Called by the setup wizard after API wallet generation.

    Args:
        account_address: Main wallet address (0x...)
        secret_key: API wallet private key (64 hex chars, no 0x prefix)
    """
    # Read existing content
    lines = []
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, 'r') as f:
            lines = f.readlines()

    # Track which keys we've updated
    updated_address = False
    updated_key = False
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('HL_ACCOUNT_ADDRESS='):
            new_lines.append(f'HL_ACCOUNT_ADDRESS={account_address}\n')
            updated_address = True
        elif stripped.startswith('HL_SECRET_KEY='):
            new_lines.append(f'HL_SECRET_KEY={secret_key}\n')
            updated_key = True
        else:
            new_lines.append(line)

    # Append if not found in existing file
    if not updated_address:
        new_lines.append(f'HL_ACCOUNT_ADDRESS={account_address}\n')
    if not updated_key:
        new_lines.append(f'HL_SECRET_KEY={secret_key}\n')

    # Atomic write (write to tmp then rename)
    tmp_path = _ENV_PATH + '.tmp'
    with open(tmp_path, 'w') as f:
        f.writelines(new_lines)
    os.replace(tmp_path, _ENV_PATH)

    # Reload dotenv so subsequent get_credentials() calls see new values
    load_dotenv(_ENV_PATH, override=True)


def ensure_database_initialized():
    """Initialize trading_data.db if it doesn't exist.
    Runs all migration SQL files from the migrations/ directory.
    Same logic as tools/init_db.py but callable from the dashboard.
    """
    db_path = os.path.join(_PROJECT_ROOT, 'trading_data.db')
    migrations_dir = os.path.join(_PROJECT_ROOT, 'migrations')

    if not os.path.isdir(migrations_dir):
        return

    # Check if DB exists and has tables (not just an empty file)
    needs_init = not os.path.exists(db_path)
    if not needs_init:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            conn.close()
            needs_init = len(tables) == 0
        except Exception:
            needs_init = True

    if not needs_init:
        return

    migration_files = sorted(glob.glob(os.path.join(migrations_dir, '*.sql')))
    if not migration_files:
        return

    conn = sqlite3.connect(db_path)
    for migration_path in migration_files:
        with open(migration_path, 'r') as f:
            sql = f.read()
        try:
            conn.executescript(sql)
            conn.commit()
        except Exception:
            pass  # Continue with other migrations (CREATE IF NOT EXISTS is safe)
    conn.close()
