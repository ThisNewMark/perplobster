"""
WebSocket Integration for Market Maker Bots
Wraps Hyperliquid WebSocket API for real-time market data and fill notifications
"""

import threading
import time
from typing import Dict, Optional, Callable
from datetime import datetime, timezone
from hyperliquid.websocket_manager import WebsocketManager
from hyperliquid.utils import constants


class MarketDataWebSocket:
    """
    Thread-safe WebSocket manager for market maker bots
    Subscribes to orderbook, fills, and user events
    """

    def __init__(self, spot_coin: str, account_address: str, pair_name: str = None, update_threshold_bps: float = 5.0, on_update_callback: Optional[Callable] = None):
        """
        Initialize WebSocket manager

        Args:
            spot_coin: Spot market identifier (e.g., "@254" for KNTQ, "@260" for XMR1)
            account_address: User wallet address for fills/events
            pair_name: Optional pair name (e.g., "PURR/USDC") for fill matching
            update_threshold_bps: Price change threshold in bps to trigger update (default: 5.0)
            on_update_callback: Optional callback when significant update occurs
        """
        self.spot_coin = spot_coin
        self.pair_name = pair_name  # e.g., "PURR/USDC"
        self.account_address = account_address
        self.update_threshold_bps = update_threshold_bps
        self.on_update_callback = on_update_callback

        # Thread locks for shared state
        self._orderbook_lock = threading.Lock()
        self._fills_lock = threading.Lock()
        self._state_lock = threading.Lock()

        # Shared state (updated by WebSocket, read by main thread)
        self._orderbook_data: Optional[Dict] = None
        self._last_orderbook_update = None
        self._new_fills = []
        self._balances: Optional[Dict] = None

        # Update flags for event-driven behavior
        self._orderbook_updated = False
        self._fills_received = False

        # Event for instant wake-up (blocks main thread until update)
        self._update_event = threading.Event()

        # Debug counters
        self._orderbook_update_count = 0
        self._last_debug_log = time.time()

        # WebSocket manager
        self.ws_manager: Optional[WebsocketManager] = None
        self.subscription_ids = []

        # Connection state
        self.connected = False
        self.error_count = 0

    def start(self):
        """Start WebSocket connections and subscriptions"""
        try:
            print("🔌 Connecting to Hyperliquid WebSocket...")

            # Create WebSocket manager
            self.ws_manager = WebsocketManager(base_url=constants.MAINNET_API_URL)

            # Start the WebSocket thread (CRITICAL!)
            self.ws_manager.start()

            # Give WebSocket thread time to connect
            time.sleep(1)
            print(f"   📡 WebSocket thread started")

            # Subscribe to orderbook updates for our spot market
            # Note: For spot markets, use @{index} format (e.g., "@260" for XMR1)
            print(f"   📊 Subscribing to orderbook for {self.spot_coin}...")
            orderbook_subscription = {"type": "l2Book", "coin": self.spot_coin}
            print(f"      Subscription: {orderbook_subscription}")
            orderbook_sub_id = self.ws_manager.subscribe(
                subscription=orderbook_subscription,
                callback=self._on_orderbook_update
            )
            self.subscription_ids.append(orderbook_sub_id)
            print(f"      Sub ID: {orderbook_sub_id}")

            # Subscribe to user fills
            print(f"   💰 Subscribing to user fills for {self.account_address[:8]}...")
            fills_sub_id = self.ws_manager.subscribe(
                subscription={"type": "userFills", "user": self.account_address},
                callback=self._on_fill
            )
            self.subscription_ids.append(fills_sub_id)

            # Subscribe to user events (for balance updates)
            print(f"   👤 Subscribing to user events...")
            events_sub_id = self.ws_manager.subscribe(
                subscription={"type": "userEvents", "user": self.account_address},
                callback=self._on_user_event
            )
            self.subscription_ids.append(events_sub_id)

            self.connected = True
            print("   ✅ WebSocket connected and subscribed")

            # Give it a moment to receive initial data
            print(f"   ℹ️  Waiting for initial orderbook data...")
            time.sleep(5)

            # Check if we've received any data yet
            if self._orderbook_update_count == 0:
                print(f"   ⚠️  No orderbook updates received yet after 5s")
                print(f"      This might indicate a subscription issue")
            else:
                print(f"   ✓ Received {self._orderbook_update_count} orderbook updates")

        except Exception as e:
            print(f"   ❌ WebSocket connection failed: {e}")
            self.connected = False
            raise

    def stop(self):
        """Stop WebSocket connections"""
        if self.ws_manager:
            print("🔌 Disconnecting WebSocket...")
            # Unsubscribe from all
            # Note: The SDK will handle cleanup when the manager is destroyed
            self.ws_manager = None
            self.connected = False
            print("   ✅ WebSocket disconnected")

    # ============================================================
    # CALLBACKS (run in WebSocket thread)
    # ============================================================

    def _on_orderbook_update(self, msg):
        """Handle orderbook update from WebSocket"""
        try:
            self._orderbook_update_count += 1

            # Debug: Log first few messages to verify callbacks work
            if self._orderbook_update_count <= 3:
                print(f"   [WS DEBUG] Orderbook callback #{self._orderbook_update_count} received!")
                print(f"      Message: {str(msg)[:200]}...")

            # Debug: Log update rate every 30 seconds
            if time.time() - self._last_debug_log > 30:
                print(f"   [WS DEBUG] Received {self._orderbook_update_count} orderbook updates in last 30s")
                self._orderbook_update_count = 0
                self._last_debug_log = time.time()

            # Parse orderbook message
            # Format: {"channel": "l2Book", "data": {"coin": "@254", "levels": [[bids], [asks]], "time": ...}}
            data = msg.get("data", {})
            levels = data.get("levels", [[], []])

            if len(levels) < 2:
                return

            bids = levels[0]
            asks = levels[1]

            if not bids or not asks:
                return

            # Calculate mid price
            best_bid = float(bids[0]["px"])
            best_ask = float(asks[0]["px"])
            mid = (best_bid + best_ask) / 2

            # Calculate depth
            bid_depth = sum(float(b["sz"]) for b in bids[:5])
            ask_depth = sum(float(a["sz"]) for a in asks[:5])

            # Update shared state with lock
            with self._orderbook_lock:
                first_update = self._orderbook_data is None

                # Check if price changed significantly (only set flag if >threshold)
                last_mid = self._orderbook_data['mid'] if self._orderbook_data else None
                significant_change = False

                if last_mid:
                    mid_change_bps = abs(mid - last_mid) / last_mid * 10000
                    if mid_change_bps > self.update_threshold_bps:
                        significant_change = True
                        print(f"   📡 WS: Price moved {mid_change_bps:.1f} bps (${last_mid:.5f} → ${mid:.5f})")

                self._orderbook_data = {
                    "mid": mid,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread": best_ask - best_bid,
                    "spread_bps": ((best_ask - best_bid) / mid) * 10000,
                    "bid_depth": bid_depth,
                    "ask_depth": ask_depth,
                    "bids": bids,
                    "asks": asks,
                    "timestamp": time.time()
                }
                self._last_orderbook_update = time.time()

                # Only set update flag if first update OR significant price change
                if first_update or significant_change:
                    self._orderbook_updated = True
                    self._update_event.set()  # Wake up main thread instantly!

                # Debug: Show first orderbook update
                if first_update:
                    print(f"   📡 WebSocket: First orderbook data received (mid: ${mid:.5f})")

            # Trigger callback if significant change
            if self.on_update_callback:
                self.on_update_callback('orderbook')

        except Exception as e:
            print(f"   ⚠️  Error processing orderbook update: {e}")
            self.error_count += 1

    def _on_fill(self, msg):
        """Handle fill notification from WebSocket"""
        try:
            # Parse fill message
            # Format: {"channel": "userFills", "data": {"isSnapshot": bool, "user": "0x...", "fills": [...]}}
            data = msg.get("data", {})
            fills = data.get("fills", [])

            # Debug: Log all fills received
            if fills:
                print(f"   [WS DEBUG] Received {len(fills)} fill(s) from WebSocket")
                for fill in fills:
                    print(f"      - Coin: {fill.get('coin')}, Side: {fill.get('side')}, Size: {fill.get('sz')}, Price: {fill.get('px')}")

            if not fills:
                return

            # Add to fills queue
            with self._fills_lock:
                for fill in fills:
                    # Check if this fill is for our market
                    # Fills can come as either spot_coin format (@254) or pair format (PURR/USDC)
                    # For HIP-3 markets, fills might come as "COPPER" but we subscribed as "xyz:COPPER"
                    fill_coin = fill.get("coin")

                    # Extract base coin name (handle "xyz:COPPER" -> "COPPER")
                    spot_coin_base = self.spot_coin.split(':')[-1] if ':' in self.spot_coin else self.spot_coin
                    pair_name_base = self.pair_name.split(':')[-1] if self.pair_name and ':' in self.pair_name else self.pair_name

                    is_our_market = (
                        fill_coin == self.spot_coin or
                        fill_coin == spot_coin_base or  # HIP-3: fill might be "COPPER" not "xyz:COPPER"
                        (self.pair_name and fill_coin == self.pair_name) or
                        (pair_name_base and fill_coin == pair_name_base)
                    )

                    if is_our_market:
                        self._new_fills.append(fill)
                        print(f"   🔔 Fill detected: {fill.get('side')} {fill.get('sz')} @ ${fill.get('px')}")
                    else:
                        print(f"   [WS DEBUG] Skipping fill for different coin: {fill_coin} (expecting {self.spot_coin} or {spot_coin_base})")

                # Check if any fills match our market (with HIP-3 handling)
                spot_coin_base = self.spot_coin.split(':')[-1] if ':' in self.spot_coin else self.spot_coin
                our_fills = [f for f in fills if f.get("coin") in [self.spot_coin, spot_coin_base, self.pair_name]]
                if our_fills:
                    self._fills_received = True
                    self._update_event.set()  # Wake up main thread instantly!

            # Trigger callback if we got fills for our market
            if self.on_update_callback and our_fills:
                self.on_update_callback('fill')

        except Exception as e:
            print(f"   ⚠️  Error processing fill: {e}")
            self.error_count += 1

    def _on_user_event(self, msg):
        """Handle user event (balance updates, etc.)"""
        try:
            # Parse user event
            # This can include balance changes, position updates, etc.
            data = msg.get("data", {})

            # Extract balance info if available
            # Note: Exact format depends on event type
            # For now, we'll just set a flag that state changed
            with self._state_lock:
                # Could parse specific balance updates here
                pass

        except Exception as e:
            print(f"   ⚠️  Error processing user event: {e}")
            self.error_count += 1

    # ============================================================
    # PUBLIC API (called from main thread)
    # ============================================================

    def get_orderbook(self) -> Optional[Dict]:
        """
        Get latest orderbook data

        Returns:
            Orderbook dict or None if not available
        """
        with self._orderbook_lock:
            return self._orderbook_data.copy() if self._orderbook_data else None

    def get_new_fills(self) -> list:
        """
        Get and clear new fills queue

        Returns:
            List of new fill dicts
        """
        with self._fills_lock:
            fills = self._new_fills.copy()
            self._new_fills.clear()
            return fills

    def check_updates(self) -> Dict[str, bool]:
        """
        Check and clear update flags (for event-driven behavior)

        Returns:
            Dict with 'orderbook' and 'fills' boolean flags
        """
        updates = {
            'orderbook': False,
            'fills': False
        }

        with self._orderbook_lock:
            updates['orderbook'] = self._orderbook_updated
            self._orderbook_updated = False

        with self._fills_lock:
            updates['fills'] = self._fills_received
            self._fills_received = False

        # Clear the event after checking
        self._update_event.clear()

        return updates

    def wait_for_update(self, timeout: float = None) -> bool:
        """
        Block until an update occurs (orderbook or fill)

        Args:
            timeout: Max seconds to wait (None = wait forever)

        Returns:
            True if update occurred, False if timeout
        """
        return self._update_event.wait(timeout=timeout)

    def is_healthy(self) -> bool:
        """
        Check if WebSocket connection is healthy

        Returns:
            True if connected and receiving data
        """
        if not self.connected:
            return False

        # Check if we've received recent orderbook updates (within last 30 seconds)
        # More lenient to allow for initial connection
        if self._last_orderbook_update:
            time_since_update = time.time() - self._last_orderbook_update
            return time_since_update < 30

        # If connected but no data yet, still return True (give it time)
        return True

    def reconnect(self):
        """
        Attempt to reconnect WebSocket

        Returns:
            True if reconnection successful, False otherwise
        """
        print("🔄 Attempting WebSocket reconnection...")

        # Stop existing connection
        self.stop()
        time.sleep(2)

        # Try to reconnect
        try:
            self.start()
            print("   ✅ WebSocket reconnected successfully")
            return True
        except Exception as e:
            print(f"   ❌ WebSocket reconnection failed: {e}")
            self.connected = False
            return False

    def get_stats(self) -> Dict:
        """Get WebSocket connection statistics"""
        return {
            'connected': self.connected,
            'healthy': self.is_healthy(),
            'error_count': self.error_count,
            'last_update': self._last_orderbook_update,
            'subscriptions': len(self.subscription_ids)
        }
