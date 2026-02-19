#!/usr/bin/env python3
"""
EMERGENCY STOP - Kill all bots and cancel all orders

Run this if:
- The dashboard is broken/unresponsive
- A bot is stuck and won't stop
- You need to immediately halt all trading

Usage:
    python tools/emergency_stop.py

    Or make it executable:
    chmod +x tools/emergency_stop.py
    ./tools/emergency_stop.py
"""

import os
import sys
import json
import signal
import subprocess

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'lib'))

def print_header():
    print("\n" + "=" * 60)
    print("  EMERGENCY STOP - Perp Lobster")
    print("=" * 60)
    print()

def kill_bot_processes():
    """Find and kill all running bot processes"""
    print("[1/3] Killing bot processes...")

    bot_scripts = ['spot_market_maker.py', 'perp_market_maker.py', 'grid_trader.py']
    killed = 0

    try:
        # Use pgrep to find Python processes running our bot scripts
        for script in bot_scripts:
            try:
                result = subprocess.run(
                    ['pgrep', '-f', script],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        try:
                            pid = int(pid)
                            os.kill(pid, signal.SIGTERM)
                            print(f"  Killed {script} (PID: {pid})")
                            killed += 1
                        except (ProcessLookupError, ValueError):
                            pass
            except Exception as e:
                pass

        if killed == 0:
            print("  No bot processes found running")
        else:
            print(f"  Killed {killed} bot process(es)")

    except Exception as e:
        print(f"  Error killing processes: {e}")

    return killed

def cancel_all_orders():
    """Connect to Hyperliquid and cancel all open orders"""
    print("\n[2/3] Cancelling all open orders on Hyperliquid...")

    # Load credentials from .env (falls back to config.json)
    try:
        from credentials import get_credentials
        creds = get_credentials()
        account_address = creds.get('account_address')
        secret_key = creds.get('secret_key')

        if not account_address or not secret_key:
            print("  Missing credentials - set HL_ACCOUNT_ADDRESS and HL_SECRET_KEY in .env")
            print("  Skipping order cancellation - cancel manually on Hyperliquid UI")
            return False

        # Try to import Hyperliquid SDK
        try:
            from hyperliquid.info import Info
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants
            from eth_account import Account
        except ImportError:
            print("  Hyperliquid SDK or eth_account not installed")
            print("  Skipping order cancellation - cancel manually on Hyperliquid UI")
            return False

        # Create wallet from secret key
        if not secret_key.startswith('0x'):
            secret_key = '0x' + secret_key
        wallet = Account.from_key(secret_key)

        # Connect to Hyperliquid with perp_dexs for HIP-3 builder markets
        info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=["", "xyz", "flx"])
        exchange = Exchange(wallet, constants.MAINNET_API_URL, perp_dexs=["", "xyz", "flx"])

        # Check all dexes (main + HIP-3 builder markets)
        dexes_to_check = ["", "xyz", "flx"]
        total_cancelled = 0
        total_found = 0

        for dex in dexes_to_check:
            dex_label = f"dex='{dex}'" if dex else "main"
            # Get all open orders for this dex
            if dex:
                open_orders = info.open_orders(account_address, dex=dex)
            else:
                open_orders = info.open_orders(account_address)

            if not open_orders:
                continue

            total_found += len(open_orders)
            print(f"  Found {len(open_orders)} open order(s) on main account ({dex_label})")

            # Cancel each order
            for order in open_orders:
                try:
                    coin = order.get('coin', 'Unknown')
                    oid = order.get('oid')

                    # Cancel the order
                    result = exchange.cancel(coin, oid)
                    if result.get('status') == 'ok':
                        print(f"  Cancelled order {oid} on {coin}")
                        total_cancelled += 1
                    else:
                        print(f"  Failed to cancel {oid}: {result}")
                except Exception as e:
                    print(f"  Error cancelling order: {e}")

        if total_found == 0:
            print("  No open orders found on main account (checked all dexes)")
        else:
            print(f"  Cancelled {total_cancelled}/{total_found} orders on main account")
        return True

    except Exception as e:
        print(f"  Error: {e}")
        print("  Cancel orders manually at: https://app.hyperliquid.xyz/trade")
        return False

def cancel_orders_all_subaccounts():
    """Try to cancel orders on all known subaccounts"""
    print("\n[3/3] Cancelling orders on subaccounts...")

    config_dir = os.path.join(PROJECT_ROOT, 'config')
    subaccounts = set()
    dexes_found = set([""])  # Always check main dex

    # Scan config files for subaccount addresses and dexes
    try:
        for filename in os.listdir(config_dir):
            if not filename.endswith('.json') or filename == 'config.json':
                continue

            filepath = os.path.join(config_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    cfg = json.load(f)

                sub_addr = cfg.get('account', {}).get('subaccount_address')
                dex = cfg.get('dex', '')  # HIP-3 dex like "xyz", "flx"
                if sub_addr:
                    subaccounts.add(sub_addr)
                if dex:
                    dexes_found.add(dex)
                    print(f"  Found dex '{dex}' in {filename}")
            except:
                pass

        if not subaccounts:
            print("  No subaccounts found in configs")
            return

        print(f"  Found {len(subaccounts)} subaccount(s), dexes: {list(dexes_found)}")

        # Load main credentials from .env
        from credentials import get_credentials
        creds = get_credentials()
        secret_key = creds.get('secret_key')
        if not secret_key:
            print("  No secret key - set HL_SECRET_KEY in .env")
            return

        from hyperliquid.info import Info
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
        from eth_account import Account

        # Create wallet
        if not secret_key.startswith('0x'):
            secret_key = '0x' + secret_key
        wallet = Account.from_key(secret_key)

        # Use perp_dexs for HIP-3 builder markets
        info = Info(constants.MAINNET_API_URL, skip_ws=True, perp_dexs=["", "xyz", "flx"])

        total_cancelled = 0
        for sub_addr in subaccounts:
            for dex in dexes_found:
                try:
                    dex_label = f"dex='{dex}'" if dex else "main"
                    # Query with dex parameter for HIP-3 markets
                    if dex:
                        open_orders = info.open_orders(sub_addr, dex=dex)
                    else:
                        open_orders = info.open_orders(sub_addr)

                    if open_orders:
                        print(f"  Subaccount {sub_addr[:10]}... ({dex_label}) has {len(open_orders)} open orders")

                        # Create exchange with vault_address for subaccount and perp_dexs for builder markets
                        exchange = Exchange(wallet, constants.MAINNET_API_URL, vault_address=sub_addr, perp_dexs=["", "xyz", "flx"])

                        for order in open_orders:
                            try:
                                coin = order.get('coin')
                                oid = order.get('oid')
                                result = exchange.cancel(coin, oid)
                                if result.get('status') == 'ok':
                                    print(f"    Cancelled {coin} order {oid}")
                                    total_cancelled += 1
                            except Exception as e:
                                print(f"    Error cancelling: {e}")
                    else:
                        print(f"  Subaccount {sub_addr[:10]}... ({dex_label}) has no open orders")
                except Exception as e:
                    print(f"  Error checking {sub_addr[:10]}... ({dex_label}): {e}")

        print(f"  Cancelled {total_cancelled} subaccount order(s)")

    except Exception as e:
        print(f"  Error checking subaccounts: {e}")

def main():
    print_header()

    # Confirm
    print("This will:")
    print("  1. Kill all running bot processes")
    print("  2. Cancel all open orders on Hyperliquid")
    print()

    response = input("Continue? [y/N]: ").strip().lower()
    if response != 'y':
        print("\nAborted.")
        return

    print()

    # Kill processes
    kill_bot_processes()

    # Cancel orders on main account
    cancel_all_orders()

    # Check subaccounts
    cancel_orders_all_subaccounts()

    print("\n" + "=" * 60)
    print("  EMERGENCY STOP COMPLETE")
    print("=" * 60)
    print("\nIf orders remain open, cancel manually at:")
    print("  https://app.hyperliquid.xyz/trade")
    print()

if __name__ == '__main__':
    main()
