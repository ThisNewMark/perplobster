#!/usr/bin/env python3
"""
Perp Lobster - Approve Builder Fee
One-time on-chain approval of the builder fee for Perp Lobster trades.

Usage:
  python scripts/approve_builder_fee.py
  python scripts/approve_builder_fee.py --subaccount 0x...
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from credentials import get_credentials, ensure_builder_fee_approved


def main():
    parser = argparse.ArgumentParser(description='Approve Perp Lobster builder fee')
    parser.add_argument('--subaccount', type=str, default=None, help='Subaccount address')
    args = parser.parse_args()

    # Load credentials
    creds = get_credentials()
    if not creds.get('secret_key'):
        print("Error: No credentials found. Edit .env with your HL_ACCOUNT_ADDRESS and HL_SECRET_KEY")
        sys.exit(1)

    secret_key = creds['secret_key']
    account = Account.from_key(secret_key)

    vault_address = args.subaccount if args.subaccount else None
    exchange = Exchange(
        wallet=account,
        base_url=constants.MAINNET_API_URL,
        vault_address=vault_address
    )

    print("Approving Perp Lobster builder fee...")
    ensure_builder_fee_approved(exchange)
    print("Done.")


if __name__ == '__main__':
    main()
