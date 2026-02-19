"""
Credentials loader
Loads account credentials and AI settings from .env file,
falling back to config.json / .ai_settings.json for backwards compatibility.
"""

import json
import os
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, '.env'))


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
