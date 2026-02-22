"""
Bot Process Manager
Handles starting, stopping, and monitoring trading bot processes
"""

import os
import sys
import json
import subprocess
import signal
import threading
import time
import queue
from datetime import datetime
from typing import Dict, Optional, List
from collections import deque


class BotProcess:
    """Represents a running bot process"""

    def __init__(self, config_file: str, process: subprocess.Popen, bot_type: str, log_callback=None):
        self.config_file = config_file
        self.process = process
        self.bot_type = bot_type
        self.started_at = datetime.now()
        self.log_buffer = deque(maxlen=200)  # Keep last 200 lines
        self._log_thread = None
        self._stop_logging = False
        self._log_callback = log_callback  # Called when new log line arrives
        self._subscribers: List[queue.Queue] = []  # SSE log subscribers
        self._subscribers_lock = threading.Lock()

    def set_log_callback(self, callback):
        """Set callback for real-time log streaming"""
        self._log_callback = callback

    def subscribe_logs(self) -> queue.Queue:
        """Subscribe to real-time log lines via a queue (for SSE streaming)"""
        q = queue.Queue(maxsize=500)
        with self._subscribers_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe_logs(self, q: queue.Queue):
        """Unsubscribe from log streaming"""
        with self._subscribers_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def start_log_capture(self):
        """Start capturing stdout/stderr in background thread"""
        self._stop_logging = False
        self._log_thread = threading.Thread(target=self._capture_logs, daemon=True)
        self._log_thread.start()

    def _capture_logs(self):
        """Background thread to capture process output"""
        try:
            while not self._stop_logging and self.process.poll() is None:
                line = self.process.stdout.readline()
                if line:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    log_line = f"[{timestamp}] {line.strip()}"
                    self.log_buffer.append(log_line)
                    # Call callback for real-time streaming
                    if self._log_callback:
                        try:
                            self._log_callback(self.config_file, log_line)
                        except Exception:
                            pass  # Don't let callback errors stop log capture
                    # Push to SSE subscribers
                    with self._subscribers_lock:
                        dead = []
                        for q in self._subscribers:
                            try:
                                q.put_nowait(log_line)
                            except queue.Full:
                                dead.append(q)
                        for q in dead:
                            self._subscribers.remove(q)
        except Exception as e:
            self.log_buffer.append(f"[ERROR] Log capture failed: {e}")

    def stop_log_capture(self):
        """Stop the log capture thread"""
        self._stop_logging = True

    @property
    def is_running(self) -> bool:
        return self.process.poll() is None

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def uptime_seconds(self) -> int:
        return int((datetime.now() - self.started_at).total_seconds())

    @property
    def uptime_str(self) -> str:
        secs = self.uptime_seconds
        if secs < 60:
            return f"{secs}s"
        elif secs < 3600:
            return f"{secs // 60}m {secs % 60}s"
        else:
            hours = secs // 3600
            mins = (secs % 3600) // 60
            return f"{hours}h {mins}m"

    def get_logs(self, n: int = 50) -> List[str]:
        """Get last n log lines"""
        return list(self.log_buffer)[-n:]

    def to_dict(self) -> dict:
        return {
            'config_file': self.config_file,
            'bot_type': self.bot_type,
            'pid': self.pid,
            'is_running': self.is_running,
            'started_at': self.started_at.isoformat(),
            'uptime': self.uptime_str,
            'uptime_seconds': self.uptime_seconds
        }


class ExternalBotProcess:
    """Wraps a bot started externally (e.g. via start.sh) that we discover by PID file.
    Reads logs from the log file instead of a subprocess pipe."""

    def __init__(self, config_file: str, pid: int, bot_type: str, log_file: str, pid_file: str):
        self.config_file = config_file
        self._pid = pid
        self.bot_type = bot_type
        self.log_file = log_file
        self.pid_file = pid_file
        # Use PID file mtime as approximate start time
        try:
            self.started_at = datetime.fromtimestamp(os.path.getmtime(pid_file))
        except OSError:
            self.started_at = datetime.now()
        self.log_buffer = deque(maxlen=200)
        self._log_thread = None
        self._stop_logging = False
        self._subscribers: List[queue.Queue] = []
        self._subscribers_lock = threading.Lock()
        self._last_log_pos = 0

        # Load existing log lines into buffer
        self._load_existing_logs()

    def _load_existing_logs(self):
        """Read existing log file into buffer."""
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    lines = f.readlines()
                    for line in lines[-200:]:
                        self.log_buffer.append(line.rstrip())
                    self._last_log_pos = f.tell()
        except Exception:
            pass

    def subscribe_logs(self) -> queue.Queue:
        q = queue.Queue(maxsize=500)
        with self._subscribers_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe_logs(self, q: queue.Queue):
        with self._subscribers_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def start_log_capture(self):
        """Tail the log file for new lines."""
        self._stop_logging = False
        self._log_thread = threading.Thread(target=self._tail_log_file, daemon=True)
        self._log_thread.start()

    def _tail_log_file(self):
        """Background thread that tails the log file."""
        try:
            while not self._stop_logging and self.is_running:
                try:
                    with open(self.log_file, 'r') as f:
                        f.seek(self._last_log_pos)
                        new_lines = f.readlines()
                        if new_lines:
                            for line in new_lines:
                                stripped = line.rstrip()
                                if stripped:
                                    self.log_buffer.append(stripped)
                                    with self._subscribers_lock:
                                        dead = []
                                        for q in self._subscribers:
                                            try:
                                                q.put_nowait(stripped)
                                            except queue.Full:
                                                dead.append(q)
                                        for q in dead:
                                            self._subscribers.remove(q)
                        self._last_log_pos = f.tell()
                except FileNotFoundError:
                    pass
                time.sleep(1)
        except Exception:
            pass

    def stop_log_capture(self):
        self._stop_logging = True

    @property
    def is_running(self) -> bool:
        try:
            os.kill(self._pid, 0)  # Signal 0 = check if alive
            return True
        except (OSError, ProcessLookupError):
            return False

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def uptime_seconds(self) -> int:
        return int((datetime.now() - self.started_at).total_seconds())

    @property
    def uptime_str(self) -> str:
        secs = self.uptime_seconds
        if secs < 60:
            return f"{secs}s"
        elif secs < 3600:
            return f"{secs // 60}m {secs % 60}s"
        else:
            hours = secs // 3600
            mins = (secs % 3600) // 60
            return f"{hours}h {mins}m"

    def get_logs(self, n: int = 50) -> List[str]:
        return list(self.log_buffer)[-n:]

    def to_dict(self) -> dict:
        return {
            'config_file': self.config_file,
            'bot_type': self.bot_type,
            'pid': self._pid,
            'is_running': self.is_running,
            'started_at': self.started_at.isoformat(),
            'uptime': self.uptime_str,
            'uptime_seconds': self.uptime_seconds,
            'external': True
        }


class BotManager:
    """
    Manages trading bot processes

    Usage:
        manager = BotManager(bots_dir='/path/to/bots', config_dir='/path/to/config')
        manager.start_bot('my_config.json')
        manager.stop_bot('my_config.json')
        status = manager.get_status('my_config.json')
    """

    # Map config types to bot scripts
    BOT_SCRIPTS = {
        'spot': 'spot_market_maker.py',
        'perp': 'perp_market_maker.py',
        'grid': 'grid_trader.py'
    }

    def __init__(self, bots_dir: str, config_dir: str):
        self.bots_dir = bots_dir
        self.config_dir = config_dir
        self.logs_dir = os.path.join(os.path.dirname(bots_dir), 'logs')
        self.processes: Dict[str, BotProcess] = {}
        self._lock = threading.Lock()
        self._log_callback = None  # Global callback for all bot logs
        self._status_callback = None  # Callback for status changes

        # Discover bots started externally (via start.sh)
        self._discover_external_bots()

        # Start cleanup thread to remove dead processes and discover new external bots
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def set_log_callback(self, callback):
        """Set callback for real-time log streaming from all bots"""
        self._log_callback = callback

    def set_status_callback(self, callback):
        """Set callback for bot status changes"""
        self._status_callback = callback

    def _notify_status_change(self, config_file: str, status: str):
        """Notify status callback of a change - runs in background thread to not block"""
        print(f"[BotManager] _notify_status_change called: {config_file} -> {status}, callback set: {self._status_callback is not None}", flush=True)
        if self._status_callback:
            # Run callback in a separate thread to avoid blocking the API response
            def run_callback():
                try:
                    full_status = self.get_status(config_file)
                    self._status_callback(config_file, status, full_status)
                    print(f"[BotManager] Status callback executed successfully", flush=True)
                except Exception as e:
                    print(f"[BotManager] Status callback error: {e}", flush=True)

            callback_thread = threading.Thread(target=run_callback, daemon=True)
            callback_thread.start()
            print(f"[BotManager] Status callback thread started", flush=True)

    def _discover_external_bots(self):
        """Scan logs/*.pid files to find bots started externally (via start.sh)."""
        if not os.path.exists(self.logs_dir):
            return

        try:
            for filename in os.listdir(self.logs_dir):
                if not filename.endswith('.pid'):
                    continue

                pid_file = os.path.join(self.logs_dir, filename)
                config_name = filename.replace('.pid', '.json')
                log_file = os.path.join(self.logs_dir, filename.replace('.pid', '.log'))

                # Skip if we already track this config
                if config_name in self.processes and self.processes[config_name].is_running:
                    continue

                try:
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())
                except (ValueError, OSError):
                    continue

                # Check if process is alive
                try:
                    os.kill(pid, 0)
                except (OSError, ProcessLookupError):
                    continue  # Dead PID, skip

                # Detect bot type from config
                config_path = os.path.join(self.config_dir, config_name)
                bot_type = 'perp'  # default
                if os.path.exists(config_path):
                    bot_type = self._detect_bot_type(config_path) or 'perp'

                ext_proc = ExternalBotProcess(config_name, pid, bot_type, log_file, pid_file)
                ext_proc.start_log_capture()
                self.processes[config_name] = ext_proc
                print(f"[BotManager] Discovered external bot: {config_name} (PID {pid})")

        except Exception as e:
            print(f"[BotManager] Error discovering external bots: {e}")

    def _cleanup_loop(self):
        """Background thread to clean up dead processes and discover new external bots"""
        while True:
            time.sleep(10)
            # Discover any newly-started external bots
            with self._lock:
                self._discover_external_bots()
            # Clean up dead processes
            with self._lock:
                dead = [k for k, v in self.processes.items() if not v.is_running]
                for config_file in dead:
                    pass  # Keep for status display

    def _detect_bot_type(self, config_path: str) -> Optional[str]:
        """Detect bot type from config file contents"""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            if 'pair' in config:
                return 'spot'
            elif 'grid' in config:
                return 'grid'
            elif 'market' in config:
                return 'perp'
            return None
        except Exception:
            return None

    def start_bot(self, config_file: str) -> dict:
        """
        Start a bot for the given config file

        Args:
            config_file: Name of config file (e.g., 'xmr_config.json')

        Returns:
            dict with success status and message
        """
        with self._lock:
            # Check if already running
            if config_file in self.processes and self.processes[config_file].is_running:
                return {
                    'success': False,
                    'error': f'Bot for {config_file} is already running (PID: {self.processes[config_file].pid})'
                }

            # Build paths
            config_path = os.path.join(self.config_dir, config_file)

            if not os.path.exists(config_path):
                return {'success': False, 'error': f'Config file not found: {config_file}'}

            # Detect bot type
            bot_type = self._detect_bot_type(config_path)
            if not bot_type:
                return {'success': False, 'error': f'Could not detect bot type from config'}

            # Get bot script
            bot_script = self.BOT_SCRIPTS.get(bot_type)
            if not bot_script:
                return {'success': False, 'error': f'Unknown bot type: {bot_type}'}

            bot_path = os.path.join(self.bots_dir, bot_script)
            if not os.path.exists(bot_path):
                return {'success': False, 'error': f'Bot script not found: {bot_script}'}

            # Start the process
            try:
                # Use the same Python interpreter that's running the dashboard
                # This ensures we use the venv's Python if dashboard is run from venv
                python_exe = sys.executable

                # Log which Python we're using (helpful for debugging)
                print(f"[BotManager] Starting {bot_type} bot with Python: {python_exe}")
                print(f"[BotManager] Config: {config_path}")
                print(f"[BotManager] Bot script: {bot_path}")

                # Explicitly inherit environment to ensure venv paths are available
                env = os.environ.copy()
                # Force unbuffered Python output so logs appear in real-time
                env['PYTHONUNBUFFERED'] = '1'

                process = subprocess.Popen(
                    [python_exe, '-u', bot_path, '--config', config_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,  # Line buffered
                    cwd=os.path.dirname(self.bots_dir),  # Run from project root
                    env=env  # Inherit environment (includes venv PATH, PYTHONPATH, etc.)
                )

                # Wait briefly to check for immediate crash
                time.sleep(0.5)

                # Check if process died immediately
                if process.poll() is not None:
                    # Process crashed - capture error output
                    error_output = process.stdout.read()
                    return {
                        'success': False,
                        'error': f'Bot crashed immediately:\n{error_output[:500]}' if error_output else 'Bot crashed immediately with no output'
                    }

                bot_proc = BotProcess(config_file, process, bot_type, log_callback=self._log_callback)
                bot_proc.start_log_capture()
                self.processes[config_file] = bot_proc
                print(f"[BotManager] Bot process tracked with key: '{config_file}' - instance: {id(self)}")
                print(f"[BotManager] Current processes: {list(self.processes.keys())}")

                # Notify status change
                self._notify_status_change(config_file, 'started')

                return {
                    'success': True,
                    'message': f'Started {bot_type} bot for {config_file}',
                    'pid': process.pid,
                    'bot_type': bot_type
                }

            except Exception as e:
                return {'success': False, 'error': f'Failed to start bot: {str(e)}'}

    def stop_bot(self, config_file: str, force: bool = False) -> dict:
        """
        Stop a running bot (works for both dashboard-started and terminal-started bots)

        Uses a two-phase approach:
        1. SIGTERM for graceful shutdown (3 second window)
        2. SIGKILL if still alive (force kill)
        """
        with self._lock:
            if config_file not in self.processes:
                return {'success': False, 'error': f'No bot running for {config_file}'}

            bot_proc = self.processes[config_file]

            if not bot_proc.is_running:
                del self.processes[config_file]
                self._cleanup_pid_file(config_file)
                return {'success': True, 'message': 'Bot was already stopped'}

            pid = bot_proc.pid
            is_external = isinstance(bot_proc, ExternalBotProcess)
            killed_forcefully = False

            try:
                bot_proc.stop_log_capture()

                if is_external:
                    # External bot: use os.kill directly
                    if force:
                        os.kill(pid, signal.SIGKILL)
                        killed_forcefully = True
                    else:
                        os.kill(pid, signal.SIGTERM)
                        time.sleep(3)
                        if bot_proc.is_running:
                            os.kill(pid, signal.SIGKILL)
                            killed_forcefully = True
                else:
                    # Dashboard-started bot: use subprocess methods
                    if force:
                        bot_proc.process.kill()
                    else:
                        bot_proc.process.terminate()
                        try:
                            bot_proc.process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            print(f"[BotManager] SIGTERM didn't stop PID {pid} within 3s, sending SIGKILL", flush=True)
                            bot_proc.process.kill()
                            killed_forcefully = True

                    try:
                        bot_proc.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.kill(pid, signal.SIGKILL)
                            time.sleep(0.5)
                        except OSError:
                            pass

                # Wait briefly then verify
                time.sleep(0.5)

                del self.processes[config_file]
                self._cleanup_pid_file(config_file)
                self._notify_status_change(config_file, 'stopped')

                method = "SIGKILL (forced)" if (force or killed_forcefully) else "SIGTERM (graceful)"
                return {
                    'success': True,
                    'message': f'Stopped bot for {config_file} (PID {pid}) via {method}'
                }

            except Exception as e:
                print(f"[BotManager] Error stopping bot {config_file}: {e}", flush=True)
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

                if config_file in self.processes:
                    del self.processes[config_file]
                self._cleanup_pid_file(config_file)
                self._notify_status_change(config_file, 'stopped')

                return {
                    'success': True,
                    'message': f'Stopped bot for {config_file} (PID {pid}) - cleanup after error: {str(e)}'
                }

    def _cleanup_pid_file(self, config_file: str):
        """Remove the PID file for a stopped bot."""
        try:
            pid_file = os.path.join(self.logs_dir, config_file.replace('.json', '.pid'))
            if os.path.exists(pid_file):
                os.remove(pid_file)
        except Exception:
            pass

    def get_status(self, config_file: str) -> dict:
        """Get status of a specific bot"""
        with self._lock:
            print(f"[BotManager] get_status('{config_file}') - processes: {list(self.processes.keys())} - instance: {id(self)}")
            if config_file not in self.processes:
                print(f"[BotManager] '{config_file}' NOT FOUND in processes")
                return {
                    'running': False,
                    'config_file': config_file
                }

            bot_proc = self.processes[config_file]
            return {
                'running': bot_proc.is_running,
                **bot_proc.to_dict()
            }

    def get_all_status(self) -> List[dict]:
        """Get status of all bots"""
        with self._lock:
            print(f"[BotManager] get_all_status called, {len(self.processes)} processes tracked: {list(self.processes.keys())}")
            result = [
                {'running': proc.is_running, **proc.to_dict()}
                for proc in self.processes.values()
            ]
            print(f"[BotManager] Returning: {result}")
            return result

    def get_logs(self, config_file: str, n: int = 50) -> dict:
        """Get recent logs for a bot"""
        with self._lock:
            if config_file not in self.processes:
                return {'success': False, 'error': 'Bot not found', 'logs': []}

            return {
                'success': True,
                'logs': self.processes[config_file].get_logs(n)
            }

    def subscribe_bot_logs(self, config_file: str):
        """Subscribe to real-time logs for a bot. Returns (queue, history) or (None, None)."""
        with self._lock:
            if config_file not in self.processes:
                return None, None
            bot = self.processes[config_file]
            q = bot.subscribe_logs()
            history = bot.get_logs(100)
            return q, history

    def unsubscribe_bot_logs(self, config_file: str, q):
        """Unsubscribe from a bot's log stream."""
        with self._lock:
            if config_file in self.processes:
                self.processes[config_file].unsubscribe_logs(q)

    def stop_all(self) -> dict:
        """Stop all running bots"""
        results = []
        config_files = list(self.processes.keys())

        for config_file in config_files:
            result = self.stop_bot(config_file)
            results.append({'config_file': config_file, **result})

        return {
            'success': True,
            'stopped': len([r for r in results if r.get('success')]),
            'results': results
        }


# Singleton instance for use across the app
_manager_instance: Optional[BotManager] = None


def get_bot_manager(bots_dir: str = None, config_dir: str = None) -> BotManager:
    """
    Get or create the singleton BotManager instance

    Args:
        bots_dir: Path to bots directory (required on first call)
        config_dir: Path to config directory (required on first call)
    """
    global _manager_instance

    if _manager_instance is None:
        if bots_dir is None or config_dir is None:
            raise ValueError("bots_dir and config_dir required on first call")
        _manager_instance = BotManager(bots_dir, config_dir)
        print(f"[BotManager] Created singleton instance: {id(_manager_instance)}")
    else:
        print(f"[BotManager] Returning existing instance: {id(_manager_instance)}")

    return _manager_instance
