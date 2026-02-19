"""
Config Editor Blueprint
Web UI for editing bot configurations without touching JSON files
Includes bot start/stop controls
"""

import os
import sys
import json
from flask import Blueprint, render_template_string, request, jsonify, redirect, url_for
from typing import Dict, Any, Optional

# Add lib to path for bot_manager import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from bot_manager import get_bot_manager, BotManager

def create_config_editor_blueprint(config_dir: str, examples_dir: str, bots_dir: str = None) -> Blueprint:
    """
    Create Flask blueprint for config editing and bot control

    Args:
        config_dir: Path to config directory (e.g., /path/to/vibetradehl/config)
        examples_dir: Path to examples directory (e.g., /path/to/vibetradehl/config/examples)
        bots_dir: Path to bots directory (e.g., /path/to/vibetradehl/bots)
    """
    bp = Blueprint('config_editor', __name__, url_prefix='/config')

    # Initialize bot manager if bots_dir provided
    bot_manager: Optional[BotManager] = None
    if bots_dir:
        print(f"[ConfigEditor] Initializing bot_manager with bots_dir={bots_dir}")
        bot_manager = get_bot_manager(bots_dir=bots_dir, config_dir=config_dir)
        print(f"[ConfigEditor] bot_manager initialized: {bot_manager is not None}, instance: {id(bot_manager) if bot_manager else 'None'}")
    else:
        print(f"[ConfigEditor] WARNING: bots_dir not provided, bot_manager will be None")

    # ========================================================================
    # HELPERS
    # ========================================================================

    def get_all_configs() -> list:
        """Get all config files from config directory"""
        configs = []
        if not os.path.exists(config_dir):
            return configs

        for filename in os.listdir(config_dir):
            if not filename.endswith('.json') or filename == 'config.json':
                continue
            filepath = os.path.join(config_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    config = json.load(f)

                # Determine type
                if 'pair' in config:
                    config_type = 'spot'
                    name = config['pair']
                elif 'grid' in config:
                    config_type = 'grid'
                    name = config.get('market', filename)
                elif 'market' in config:
                    config_type = 'perp'
                    name = f"{config['market']}-PERP"
                else:
                    continue

                configs.append({
                    'filename': filename,
                    'filepath': filepath,
                    'name': name,
                    'type': config_type,
                    'description': config.get('description', ''),
                    'config': config
                })
            except Exception as e:
                print(f"Error loading {filename}: {e}")
                continue

        configs.sort(key=lambda x: x['name'])
        return configs

    def get_example_configs() -> list:
        """Get example configs from examples directory"""
        examples = []
        if not os.path.exists(examples_dir):
            return examples

        for filename in os.listdir(examples_dir):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(examples_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    config = json.load(f)

                if 'pair' in config:
                    config_type = 'spot'
                elif 'grid' in config:
                    config_type = 'grid'
                elif 'market' in config:
                    config_type = 'perp'
                else:
                    continue

                examples.append({
                    'filename': filename,
                    'type': config_type,
                    'description': config.get('description', filename)
                })
            except:
                continue
        return examples

    # ========================================================================
    # ROUTES
    # ========================================================================

    @bp.route('/')
    def config_list():
        """List all configs with edit/delete options"""
        configs = get_all_configs()
        examples = get_example_configs()
        return render_template_string(CONFIG_LIST_TEMPLATE, configs=configs, examples=examples)

    @bp.route('/edit/<filename>')
    def edit_config(filename: str):
        """Edit a specific config file"""
        filepath = os.path.join(config_dir, filename)
        if not os.path.exists(filepath):
            return redirect('/config')

        try:
            with open(filepath, 'r') as f:
                config = json.load(f)
        except Exception as e:
            return f"Error loading config: {e}", 500

        # Determine type
        if 'pair' in config:
            config_type = 'spot'
        elif 'grid' in config:
            config_type = 'grid'
        elif 'market' in config:
            config_type = 'perp'
        else:
            config_type = 'unknown'

        return render_template_string(
            CONFIG_EDITOR_TEMPLATE,
            config=config,
            config_type=config_type,
            filename=filename,
            is_new=False
        )

    @bp.route('/new')
    def new_config():
        """Create a new config from template"""
        template_type = request.args.get('type', 'spot')

        # Load example as base
        example_map = {
            'spot': 'spot_example.json',
            'perp': 'perp_example.json',
            'grid': 'grid_example.json'
        }

        example_file = os.path.join(examples_dir, example_map.get(template_type, 'spot_example.json'))

        try:
            with open(example_file, 'r') as f:
                config = json.load(f)
        except:
            config = {}

        return render_template_string(
            CONFIG_EDITOR_TEMPLATE,
            config=config,
            config_type=template_type,
            filename='',
            is_new=True
        )

    @bp.route('/api/save', methods=['POST'])
    def save_config():
        """Save config to file"""
        try:
            data = request.json
            filename = data.get('filename', '').strip()
            config = data.get('config', {})
            is_new = data.get('is_new', False)

            if not filename:
                return jsonify({'success': False, 'error': 'Filename is required'}), 400

            # Ensure .json extension
            if not filename.endswith('.json'):
                filename += '.json'

            # Sanitize filename
            filename = filename.replace('/', '_').replace('\\', '_')

            filepath = os.path.join(config_dir, filename)

            # Don't overwrite existing file if creating new
            if is_new and os.path.exists(filepath):
                return jsonify({'success': False, 'error': f'File {filename} already exists'}), 400

            # Write config
            with open(filepath, 'w') as f:
                json.dump(config, f, indent=2)

            return jsonify({
                'success': True,
                'filename': filename,
                'message': f'Saved {filename}'
            })

        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/delete/<filename>', methods=['DELETE'])
    def delete_config(filename: str):
        """Delete a config file"""
        try:
            filepath = os.path.join(config_dir, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
                return jsonify({'success': True, 'message': f'Deleted {filename}'})
            else:
                return jsonify({'success': False, 'error': 'File not found'}), 404
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/load/<filename>')
    def load_config(filename: str):
        """Load a config file as JSON"""
        try:
            filepath = os.path.join(config_dir, filename)
            with open(filepath, 'r') as f:
                config = json.load(f)
            return jsonify({'success': True, 'config': config})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # ========================================================================
    # BOT CONTROL ROUTES
    # ========================================================================

    @bp.route('/api/bot/start/<filename>', methods=['POST'])
    def start_bot(filename: str):
        """Start a bot for the given config"""
        if not bot_manager:
            return jsonify({'success': False, 'error': 'Bot manager not initialized'}), 500
        result = bot_manager.start_bot(filename)
        return jsonify(result)

    @bp.route('/api/bot/stop/<filename>', methods=['POST'])
    def stop_bot(filename: str):
        """Stop a running bot"""
        if not bot_manager:
            return jsonify({'success': False, 'error': 'Bot manager not initialized'}), 500
        force = request.args.get('force', 'false').lower() == 'true'
        result = bot_manager.stop_bot(filename, force=force)
        return jsonify(result)

    @bp.route('/api/bot/status/<filename>')
    def bot_status(filename: str):
        """Get status of a specific bot"""
        print(f"[API] Checking bot status for: {filename}, bot_manager={bot_manager is not None}")
        if not bot_manager:
            print(f"[API] ERROR: bot_manager is None!")
            return jsonify({'running': False, 'error': 'Bot manager not initialized'})
        status = bot_manager.get_status(filename)
        print(f"[API] Status for {filename}: {status}")
        return jsonify(status)

    @bp.route('/api/bot/status')
    def all_bot_status():
        """Get status of all bots"""
        if not bot_manager:
            return jsonify({'bots': [], 'error': 'Bot manager not initialized'})
        statuses = bot_manager.get_all_status()
        print(f"[API] Bot statuses: {statuses}")
        return jsonify({'bots': statuses})

    @bp.route('/api/bot/logs/<filename>')
    def bot_logs(filename: str):
        """Get recent logs for a bot"""
        if not bot_manager:
            return jsonify({'success': False, 'error': 'Bot manager not initialized', 'logs': []})
        n = request.args.get('n', 50, type=int)
        return jsonify(bot_manager.get_logs(filename, n))

    @bp.route('/api/bot/stop-all', methods=['POST'])
    def stop_all_bots():
        """Stop all running bots"""
        if not bot_manager:
            return jsonify({'success': False, 'error': 'Bot manager not initialized'})
        return jsonify(bot_manager.stop_all())

    return bp


# ============================================================================
# CONFIG LIST TEMPLATE
# ============================================================================

CONFIG_LIST_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Config Manager - Perp Lobster</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            background: #0a0e27;
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 25px;
            background: linear-gradient(135deg, #1a1f3a 0%, #2a2f4a 100%);
            border-radius: 12px;
            margin-bottom: 30px;
            border: 1px solid #00ccff;
        }
        .header h1 { color: #00ccff; font-size: 24px; }
        .header-actions { display: flex; gap: 10px; }

        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #00ccff;
            color: #0a0e27;
        }
        .btn-primary:hover { background: #00a3cc; }
        .btn-secondary {
            background: #2a2f4a;
            color: #e0e0e0;
            border: 1px solid #3a3f5a;
        }
        .btn-secondary:hover { background: #3a3f5a; }
        .btn-danger {
            background: #f87171;
            color: white;
        }
        .btn-danger:hover { background: #dc2626; }
        .btn-small {
            padding: 6px 12px;
            font-size: 11px;
        }

        .section-title {
            font-size: 16px;
            color: #00ccff;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #2a2f4a;
        }

        .config-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }

        .config-card {
            background: #1a1f3a;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #2a2f4a;
            transition: all 0.2s;
        }
        .config-card:hover {
            border-color: #00ccff;
        }

        .config-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 12px;
        }
        .config-name {
            font-size: 18px;
            font-weight: 600;
            color: #fff;
        }
        .config-type {
            padding: 3px 8px;
            border-radius: 10px;
            font-size: 10px;
            text-transform: uppercase;
            font-weight: 600;
        }
        .config-type.spot { background: #10b981; color: white; }
        .config-type.perp { background: #f59e0b; color: white; }
        .config-type.grid { background: #8b5cf6; color: white; }

        .config-desc {
            font-size: 12px;
            color: #8b92b0;
            margin-bottom: 15px;
            line-height: 1.5;
        }
        .config-file {
            font-size: 11px;
            color: #6b7280;
            margin-bottom: 15px;
            font-family: monospace;
        }

        .config-actions {
            display: flex;
            gap: 8px;
        }

        .new-config-options {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .template-btn {
            padding: 15px 25px;
            background: #1a1f3a;
            border: 1px solid #2a2f4a;
            border-radius: 8px;
            color: #e0e0e0;
            cursor: pointer;
            transition: all 0.2s;
            text-align: center;
        }
        .template-btn:hover {
            border-color: #00ccff;
            background: #2a2f4a;
        }
        .template-btn .type {
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 5px;
        }
        .template-btn .desc {
            font-size: 11px;
            color: #8b92b0;
        }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #8b92b0;
        }

        .back-link {
            color: #00ccff;
            text-decoration: none;
            font-size: 13px;
        }
        .back-link:hover { text-decoration: underline; }

        /* Bot status styles */
        .btn-success {
            background: #10b981;
            color: white;
        }
        .btn-success:hover { background: #059669; }
        .btn-warning {
            background: #f59e0b;
            color: white;
        }
        .btn-warning:hover { background: #d97706; }

        .bot-status {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 12px;
            padding: 8px 12px;
            background: #0a0e27;
            border-radius: 6px;
            font-size: 12px;
        }
        .status-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #6b7280;
        }
        .status-indicator.running {
            background: #10b981;
            animation: pulse 2s infinite;
        }
        .status-indicator.stopped { background: #6b7280; }
        @keyframes pulse {
            0%,100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .status-text { color: #8b92b0; }
        .status-text.running { color: #10b981; }
        .uptime { color: #6b7280; font-size: 11px; }

        .bot-controls {
            display: flex;
            gap: 6px;
            margin-top: 10px;
        }

        .logs-btn {
            background: transparent;
            border: 1px solid #3a3f5a;
            color: #8b92b0;
            padding: 4px 8px;
            font-size: 10px;
            border-radius: 4px;
            cursor: pointer;
        }
        .logs-btn:hover {
            border-color: #00ccff;
            color: #00ccff;
        }

        /* Logs modal */
        .logs-modal .modal-content {
            max-width: 700px;
            width: 90%;
            max-height: 80vh;
            text-align: left;
        }
        .logs-modal h3 { color: #00ccff; }
        .logs-container {
            background: #0a0e27;
            border-radius: 6px;
            padding: 15px;
            max-height: 400px;
            overflow-y: auto;
            font-size: 11px;
            line-height: 1.6;
            margin-top: 15px;
        }
        .log-line {
            font-family: 'SF Mono', Monaco, monospace;
            color: #8b92b0;
            white-space: pre-wrap;
            word-break: break-all;
        }
        .log-line.error { color: #f87171; }
        .log-line.warning { color: #f59e0b; }

        /* Live streaming indicator */
        .live-indicator {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #10b981;
            color: white;
            padding: 3px 10px;
            border-radius: 10px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            margin-left: 10px;
        }
        .live-indicator.hidden { display: none; }
        .live-indicator .dot {
            width: 6px;
            height: 6px;
            background: white;
            border-radius: 50%;
            animation: livePulse 1s infinite;
        }
        @keyframes livePulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        .logs-header {
            display: flex;
            align-items: center;
        }

        /* Stop all button */
        .header-actions {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .running-count {
            background: #10b981;
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .ws-status {
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 10px;
            color: #6b7280;
            padding: 4px 8px;
            background: #1a1f3a;
            border-radius: 8px;
        }
        .ws-status .ws-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #6b7280;
        }
        .ws-status.connected .ws-dot { background: #10b981; }
        .ws-status.connected { color: #10b981; }
        .ws-status.connecting .ws-dot {
            background: #f59e0b;
            animation: pulse 1s infinite;
        }
        .ws-status.connecting { color: #f59e0b; }

        /* Modal for delete confirmation */
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.7);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .modal.active { display: flex; }
        .modal-content {
            background: #1a1f3a;
            padding: 30px;
            border-radius: 12px;
            border: 1px solid #00ccff;
            max-width: 400px;
            text-align: center;
        }
        .modal-content h3 { margin-bottom: 15px; color: #f87171; }
        .modal-content p { margin-bottom: 20px; color: #8b92b0; }
        .modal-actions { display: flex; gap: 10px; justify-content: center; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>Config Manager</h1>
                <a href="/" class="back-link">&larr; Back to Dashboard</a>
                &nbsp;|&nbsp;
                <a href="/ai" class="back-link" style="color: #8b5cf6;" title="AI Settings">⚙️</a>
            </div>
            <div class="header-actions">
                <div class="ws-status connecting" id="wsStatus">
                    <span class="ws-dot"></span>
                    <span id="wsStatusText">Connecting...</span>
                </div>
                <span class="running-count" id="runningCount" style="display: none;">0 running</span>
                <button class="btn btn-danger btn-small" id="stopAllBtn" onclick="stopAllAndCancel()" title="Stop all bots and cancel orders" style="display: none;">Stop All</button>
            </div>
        </div>

        <!-- New Config Section -->
        <div class="section-title">Create New Config</div>
        <div class="new-config-options" style="margin-bottom: 40px;">
            <a href="/config/new?type=spot" class="template-btn">
                <div class="type">Spot Market Maker</div>
                <div class="desc">For HIP-1 spot tokens with perp oracle</div>
            </a>
            <a href="/config/new?type=perp" class="template-btn">
                <div class="type">Perp Market Maker</div>
                <div class="desc">For perpetual futures markets</div>
            </a>
            <a href="/config/new?type=grid" class="template-btn">
                <div class="type">Grid Trader</div>
                <div class="desc">Range-bound grid trading</div>
            </a>
        </div>

        <!-- Existing Configs -->
        <div class="section-title">Existing Configs ({{ configs|length }})</div>
        {% if configs %}
        <div class="config-grid">
            {% for cfg in configs %}
            <div class="config-card" data-filename="{{ cfg.filename }}">
                <div class="config-header">
                    <div class="config-name">{{ cfg.name }}</div>
                    <div class="config-type {{ cfg.type }}">{{ cfg.type }}</div>
                </div>
                <div class="config-desc">{{ cfg.description or 'No description' }}</div>
                <div class="config-file">{{ cfg.filename }}</div>

                <!-- Bot Status -->
                <div class="bot-status" id="status-{{ cfg.filename | replace('.', '-') }}">
                    <div class="status-indicator stopped"></div>
                    <span class="status-text">Stopped</span>
                    <span class="uptime"></span>
                </div>

                <!-- Bot Controls -->
                <div class="bot-controls">
                    <button class="btn btn-success btn-small start-btn" onclick='startBot({{ cfg.filename | tojson }})'>Start</button>
                    <button class="btn btn-warning btn-small stop-btn" onclick='stopBot({{ cfg.filename | tojson }})' style="display: none;">Stop</button>
                    <button class="logs-btn" onclick='showLogs({{ cfg.filename | tojson }}, {{ cfg.name | tojson }})'>Logs</button>
                </div>

                <div class="config-actions" style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #2a2f4a;">
                    <a href="/config/edit/{{ cfg.filename }}" class="btn btn-primary btn-small">Edit</a>
                    <button class="btn btn-danger btn-small" onclick='confirmDelete({{ cfg.filename | tojson }}, {{ cfg.name | tojson }})'>Delete</button>
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="empty-state">
            <p>No configs found. Create one above to get started.</p>
        </div>
        {% endif %}
    </div>

    <!-- Delete Confirmation Modal -->
    <div class="modal" id="deleteModal">
        <div class="modal-content">
            <h3>Delete Config?</h3>
            <p>Are you sure you want to delete <strong id="deleteFileName"></strong>?</p>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="closeModal('deleteModal')">Cancel</button>
                <button class="btn btn-danger" id="confirmDeleteBtn">Delete</button>
            </div>
        </div>
    </div>

    <!-- Logs Modal -->
    <div class="modal logs-modal" id="logsModal">
        <div class="modal-content">
            <div class="logs-header">
                <h3>Logs: <span id="logsConfigName"></span></h3>
                <span class="live-indicator hidden" id="liveIndicator">
                    <span class="dot"></span>
                    LIVE
                </span>
            </div>
            <div class="logs-container" id="logsContainer">
                <div class="log-line">No logs available</div>
            </div>
            <div class="modal-actions" style="margin-top: 15px;">
                <button class="btn btn-secondary" onclick="closeModal('logsModal')">Close</button>
                <button class="btn btn-primary" id="refreshLogsBtn" onclick="refreshLogs()">Refresh</button>
            </div>
        </div>
    </div>

    <script>
        console.log('[PerpLobster] Config Manager script loading...');

        let deleteTarget = null;
        let logsTarget = null;
        let statusInterval = null;
        let socket = null;
        let useWebSocket = false;

        // =====================================================================
        // WEBSOCKET CONNECTION
        // =====================================================================

        function initWebSocket() {
            console.log('[PerpLobster] Attempting WebSocket initialization...');
            console.log('[PerpLobster] io object exists:', typeof io !== 'undefined');

            if (typeof io === 'undefined') {
                console.log('[PerpLobster] Socket.IO library not loaded - check CDN or network');
                return false;
            }

            try {
                console.log('[PerpLobster] Creating Socket.IO connection...');
                socket = io({
                    transports: ['websocket', 'polling'],
                    reconnection: true,
                    reconnectionAttempts: 5,
                    reconnectionDelay: 1000
                });

                socket.on('connect_error', function(err) {
                    console.error('[PerpLobster] Connection error:', err.message);
                    updateWsStatus('disconnected');
                });

                // Timeout: if not connected within 5 seconds, fall back to polling
                setTimeout(function() {
                    if (!socket.connected) {
                        console.log('[PerpLobster] WebSocket connection timeout, falling back to polling');
                        updateWsStatus('disconnected');
                        startPolling();
                        // Do initial fetch
                        refreshAllStatus().then(updateRunningCount);
                    }
                }, 5000);

                socket.on('connect', function() {
                    console.log('[PerpLobster] WebSocket connected!');
                    useWebSocket = true;
                    updateWsStatus('connected');
                    // Stop polling if it was running
                    if (statusInterval) {
                        clearInterval(statusInterval);
                        statusInterval = null;
                    }
                    // Get initial status
                    socket.emit('get_all_status');
                });

                socket.on('disconnect', function() {
                    console.log('[PerpLobster] WebSocket disconnected, falling back to polling');
                    useWebSocket = false;
                    updateWsStatus('disconnected');
                    startPolling();
                });

                socket.on('connected', function(data) {
                    console.log('[PerpLobster] Server confirmed connection:', data);
                });

                socket.on('bot_log', function(data) {
                    // Real-time log line from a bot
                    if (logsTarget && data.config_file === logsTarget) {
                        appendLogLine(data.line);
                    }
                });

                socket.on('log_history', function(data) {
                    // Received log history for a bot
                    if (data.config_file === logsTarget) {
                        displayLogs(data.logs);
                    }
                });

                socket.on('bot_status', function(data) {
                    // Real-time status update
                    console.log('[PerpLobster] Status update:', data);
                    if (data.status === 'started') {
                        updateCardStatus(data.config_file, true, data.data.pid, data.data.uptime);
                    } else if (data.status === 'stopped') {
                        updateCardStatus(data.config_file, false);
                    }
                    updateRunningCount();
                });

                socket.on('all_status', function(data) {
                    // Full status update for all bots
                    handleAllStatus(data.bots);
                });

                socket.on('error', function(data) {
                    console.error('[PerpLobster] WebSocket error:', data.message);
                });

                return true;
            } catch (err) {
                console.error('[PerpLobster] Failed to init WebSocket:', err);
                return false;
            }
        }

        function handleAllStatus(bots) {
            // Reset all cards to stopped first
            document.querySelectorAll('.config-card').forEach(card => {
                const filename = card.dataset.filename;
                updateCardStatus(filename, false);
            });

            // Update running bots
            if (bots && bots.length > 0) {
                bots.forEach(bot => {
                    if (bot.running) {
                        updateCardStatus(bot.config_file, true, bot.pid, bot.uptime);
                    }
                });
            }

            updateRunningCount();
        }

        function updateRunningCount() {
            const runningBots = document.querySelectorAll('.status-indicator.running').length;
            const countEl = document.getElementById('runningCount');
            const stopAllBtn = document.getElementById('stopAllBtn');

            if (runningBots > 0) {
                if (countEl) {
                    countEl.textContent = runningBots + ' running';
                    countEl.style.display = 'inline-block';
                }
                if (stopAllBtn) stopAllBtn.style.display = 'inline-block';
            } else {
                if (countEl) countEl.style.display = 'none';
                if (stopAllBtn) stopAllBtn.style.display = 'none';
            }
        }

        function startPolling() {
            if (statusInterval) return; // Already polling
            console.log('[PerpLobster] Starting status polling...');
            statusInterval = setInterval(refreshAllStatus, 5000);
        }

        function updateWsStatus(status) {
            const wsStatusEl = document.getElementById('wsStatus');
            const wsTextEl = document.getElementById('wsStatusText');
            wsStatusEl.className = 'ws-status ' + status;
            if (status === 'connected') {
                wsTextEl.textContent = 'Live';
            } else if (status === 'connecting') {
                wsTextEl.textContent = 'Connecting...';
            } else {
                wsTextEl.textContent = 'Polling';
            }
        }

        // =====================================================================
        // DELETE FUNCTIONALITY
        // =====================================================================

        function confirmDelete(filename, name) {
            deleteTarget = filename;
            document.getElementById('deleteFileName').textContent = name;
            document.getElementById('deleteModal').classList.add('active');
        }

        function closeModal(modalId) {
            document.getElementById(modalId).classList.remove('active');
            if (modalId === 'deleteModal') deleteTarget = null;
            if (modalId === 'logsModal') {
                logsTarget = null;
                // Reset live indicator
                document.getElementById('liveIndicator').classList.add('hidden');
                document.getElementById('refreshLogsBtn').style.display = 'inline-block';
            }
        }

        const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
        if (confirmDeleteBtn) {
            confirmDeleteBtn.onclick = async () => {
                if (!deleteTarget) return;

                try {
                    const resp = await fetch('/config/api/delete/' + deleteTarget, { method: 'DELETE' });
                    const data = await resp.json();

                    if (data.success) {
                        document.querySelector('[data-filename="' + deleteTarget + '"]').remove();
                        closeModal('deleteModal');
                    } else {
                        alert('Error: ' + data.error);
                    }
                } catch (err) {
                    alert('Error deleting config: ' + err.message);
                }
            };
        }

        // Close modals on background click
        document.querySelectorAll('.modal').forEach(modal => {
            modal.onclick = (e) => {
                if (e.target === modal) closeModal(modal.id);
            };
        });

        // =====================================================================
        // BOT CONTROL FUNCTIONALITY
        // =====================================================================
        console.log('[PerpLobster] Defining bot control functions...');

        async function startBot(filename) {
            console.log('[PerpLobster] startBot called with:', filename);
            var card = document.querySelector('[data-filename="' + filename + '"]');
            if (!card) {
                console.error('[PerpLobster] Card not found for:', filename);
                return;
            }
            var startBtn = card.querySelector('.start-btn');
            startBtn.textContent = 'Starting...';
            startBtn.disabled = true;

            try {
                // Add timeout to prevent hanging (30 seconds for bot startup)
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 30000);

                var resp = await fetch('/config/api/bot/start/' + filename, {
                    method: 'POST',
                    signal: controller.signal
                });
                clearTimeout(timeoutId);

                const data = await resp.json();
                console.log('[PerpLobster] Start response:', data);

                if (data.success) {
                    updateCardStatus(filename, true, data.pid);
                    updateRunningCount();
                } else {
                    var errorMsg = data.error || 'Unknown error';
                    if (errorMsg.includes('ModuleNotFoundError') || errorMsg.includes('No module named')) {
                        alert('Bot crashed - missing dependency! Run: pip install -r requirements.txt');
                    } else {
                        alert('Failed to start bot: ' + errorMsg);
                    }
                    startBtn.textContent = 'Start';
                    startBtn.disabled = false;
                }
            } catch (err) {
                console.error('[PerpLobster] Start error:', err);
                // Always check if bot started despite error (including timeout)
                console.log('[PerpLobster] Checking if bot started despite error...');
                setTimeout(async () => {
                    await refreshAllStatus();
                    updateRunningCount();
                }, 1000);
            }
        }

        async function stopBot(filename) {
            var card = document.querySelector('[data-filename="' + filename + '"]');
            var stopBtn = card.querySelector('.stop-btn');
            stopBtn.textContent = 'Stopping...';
            stopBtn.disabled = true;

            try {
                var resp = await fetch('/config/api/bot/stop/' + filename, { method: 'POST' });
                const data = await resp.json();

                console.log('[PerpLobster] Stop response:', data);
                if (data.success) {
                    updateCardStatus(filename, false);
                    updateRunningCount();
                } else {
                    alert('Failed to stop bot: ' + data.error);
                    stopBtn.textContent = 'Stop';
                    stopBtn.disabled = false;
                }
            } catch (err) {
                alert('Error stopping bot: ' + err.message);
                stopBtn.textContent = 'Stop';
                stopBtn.disabled = false;
            }
        }

        async function stopAllBots() {
            if (!confirm('Stop all running bots?')) return;

            try {
                const resp = await fetch('/config/api/bot/stop-all', { method: 'POST' });
                const data = await resp.json();

                if (data.success) {
                    // Refresh all statuses
                    await refreshAllStatus();
                } else {
                    alert('Error: ' + data.error);
                }
            } catch (err) {
                alert('Error stopping bots: ' + err.message);
            }
        }

        function updateCardStatus(filename, running, pid, uptime) {
            console.log('[PerpLobster] updateCardStatus called:', filename, 'running:', running, 'pid:', pid);
            pid = pid || null;
            uptime = uptime || '';
            var safeId = filename.replace(/[.]/g, '-');
            var statusDiv = document.getElementById('status-' + safeId);
            console.log('[PerpLobster] statusDiv:', statusDiv ? 'found' : 'NOT FOUND', 'id:', 'status-' + safeId);
            if (!statusDiv) return;

            var card = document.querySelector('[data-filename="' + filename + '"]');
            console.log('[PerpLobster] card:', card ? 'found' : 'NOT FOUND');
            var indicator = statusDiv.querySelector('.status-indicator');
            var text = statusDiv.querySelector('.status-text');
            var uptimeSpan = statusDiv.querySelector('.uptime');
            var startBtn = card.querySelector('.start-btn');
            var stopBtn = card.querySelector('.stop-btn');

            if (running) {
                indicator.className = 'status-indicator running';
                text.className = 'status-text running';
                text.textContent = 'Running (PID: ' + (pid || '?') + ')';
                uptimeSpan.textContent = uptime ? '- ' + uptime : '';
                startBtn.style.display = 'none';
                stopBtn.style.display = 'inline-block';
                stopBtn.textContent = 'Stop';
                stopBtn.disabled = false;
            } else {
                indicator.className = 'status-indicator stopped';
                text.className = 'status-text';
                text.textContent = 'Stopped';
                uptimeSpan.textContent = '';
                startBtn.style.display = 'inline-block';
                startBtn.textContent = 'Start';
                startBtn.disabled = false;
                stopBtn.style.display = 'none';
            }
        }

        async function refreshAllStatus() {
            try {
                const resp = await fetch('/config/api/bot/status');
                const data = await resp.json();

                // Reset all cards to stopped first
                document.querySelectorAll('.config-card').forEach(card => {
                    const filename = card.dataset.filename;
                    updateCardStatus(filename, false);
                });

                // Update running bots
                let runningCount = 0;
                if (data.bots) {
                    data.bots.forEach(bot => {
                        if (bot.running) {
                            runningCount++;
                            updateCardStatus(bot.config_file, true, bot.pid, bot.uptime);
                        }
                    });
                }

                // Update header
                const countEl = document.getElementById('runningCount');
                const stopAllBtn = document.getElementById('stopAllBtn');
                if (runningCount > 0) {
                    if (countEl) {
                        countEl.textContent = runningCount + ' running';
                        countEl.style.display = 'inline-block';
                    }
                    if (stopAllBtn) stopAllBtn.style.display = 'inline-block';
                } else {
                    if (countEl) countEl.style.display = 'none';
                    if (stopAllBtn) stopAllBtn.style.display = 'none';
                }

            } catch (err) {
                console.error('Error fetching status:', err);
            }
        }

        // =====================================================================
        // LOGS FUNCTIONALITY
        // =====================================================================

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatLogLine(line) {
            let className = 'log-line';
            if (line.toLowerCase().includes('error')) className += ' error';
            else if (line.toLowerCase().includes('warn')) className += ' warning';
            return '<div class="' + className + '">' + escapeHtml(line) + '</div>';
        }

        function displayLogs(logs) {
            const container = document.getElementById('logsContainer');
            if (logs && logs.length > 0) {
                container.innerHTML = logs.map(formatLogLine).join('');
                container.scrollTop = container.scrollHeight;
            } else {
                container.innerHTML = '<div class="log-line">No logs available. Bot may not be running.</div>';
            }
        }

        function appendLogLine(line) {
            const container = document.getElementById('logsContainer');
            // Remove "No logs" or "Loading" placeholder if present
            const placeholder = container.querySelector('.log-line:only-child');
            if (placeholder && (placeholder.textContent.includes('No logs') || placeholder.textContent.includes('Loading'))) {
                container.innerHTML = '';
            }
            container.insertAdjacentHTML('beforeend', formatLogLine(line));
            // Auto-scroll to bottom
            container.scrollTop = container.scrollHeight;
        }

        async function showLogs(filename, name) {
            logsTarget = filename;
            document.getElementById('logsConfigName').textContent = name;
            document.getElementById('logsModal').classList.add('active');

            const liveIndicator = document.getElementById('liveIndicator');
            const refreshBtn = document.getElementById('refreshLogsBtn');

            // If WebSocket is connected, subscribe for real-time logs
            if (useWebSocket && socket && socket.connected) {
                document.getElementById('logsContainer').innerHTML = '<div class="log-line">Connecting to log stream...</div>';
                socket.emit('subscribe_logs', { config_file: filename });
                // Show live indicator, hide refresh button
                liveIndicator.classList.remove('hidden');
                refreshBtn.style.display = 'none';
            } else {
                // Fallback to HTTP fetch
                liveIndicator.classList.add('hidden');
                refreshBtn.style.display = 'inline-block';
                await refreshLogs();
            }
        }

        async function refreshLogs() {
            if (!logsTarget) return;

            const container = document.getElementById('logsContainer');
            container.innerHTML = '<div class="log-line">Loading...</div>';

            try {
                var resp = await fetch('/config/api/bot/logs/' + logsTarget + '?n=100');
                const data = await resp.json();
                displayLogs(data.logs);
            } catch (err) {
                container.innerHTML = '<div class="log-line error">Error loading logs: ' + err.message + '</div>';
            }
        }

        // =====================================================================
        // INITIALIZATION
        // =====================================================================

        try {
            console.log('[PerpLobster] Initializing...');
            updateWsStatus('connecting');

            // Try WebSocket first
            if (initWebSocket()) {
                console.log('[PerpLobster] WebSocket initialized, waiting for connection...');
                // Connection status will be updated by socket.on('connect')
            } else {
                console.log('[PerpLobster] WebSocket not available, using polling');
                updateWsStatus('disconnected');
                // Initial status check via HTTP
                refreshAllStatus().then(() => {
                    console.log('[PerpLobster] Initial status check complete');
                    updateRunningCount();
                }).catch(err => {
                    console.error('[PerpLobster] Initial status check failed:', err);
                });
                // Start polling
                startPolling();
            }

            console.log('[PerpLobster] Config Manager ready!');
        } catch (initErr) {
            console.error('[PerpLobster] Initialization error:', initErr);
            updateWsStatus('disconnected');
            // Fallback to polling on any error
            startPolling();
        }

        // Stop All and Cancel Orders
        async function stopAllAndCancel() {
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
                refreshAllStatus();
                updateRunningCount();
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
# CONFIG EDITOR TEMPLATE
# ============================================================================

CONFIG_EDITOR_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>{{ "New Config" if is_new else "Edit " + filename }} - Perp Lobster</title>
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
        .container { max-width: 900px; margin: 0 auto; }

        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 25px;
            background: linear-gradient(135deg, #1a1f3a 0%, #2a2f4a 100%);
            border-radius: 12px;
            margin-bottom: 30px;
            border: 1px solid #00ccff;
        }
        .header h1 { color: #00ccff; font-size: 22px; }

        .back-link {
            color: #00ccff;
            text-decoration: none;
            font-size: 13px;
        }
        .back-link:hover { text-decoration: underline; }

        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #00ccff;
            color: #0a0e27;
        }
        .btn-primary:hover { background: #00a3cc; }
        .btn-secondary {
            background: #2a2f4a;
            color: #e0e0e0;
            border: 1px solid #3a3f5a;
        }
        .btn-secondary:hover { background: #3a3f5a; }

        .form-section {
            background: #1a1f3a;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 20px;
            border: 1px solid #2a2f4a;
        }
        .section-title {
            font-size: 16px;
            color: #00ccff;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #2a2f4a;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .section-icon {
            width: 24px;
            height: 24px;
            background: #00ccff;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            color: #0a0e27;
        }

        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
        }
        .form-group.full-width {
            grid-column: 1 / -1;
        }

        label {
            font-size: 11px;
            color: #8b92b0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }

        input, select, textarea {
            padding: 10px 12px;
            background: #0a0e27;
            border: 1px solid #3a3f5a;
            border-radius: 6px;
            color: #e0e0e0;
            font-family: inherit;
            font-size: 14px;
            transition: border-color 0.2s;
        }
        input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: #00ccff;
        }
        input:invalid {
            border-color: #f87171;
        }

        .help-text {
            font-size: 10px;
            color: #6b7280;
            margin-top: 4px;
        }

        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .checkbox-group input[type="checkbox"] {
            width: 18px;
            height: 18px;
        }
        .checkbox-group label {
            margin-bottom: 0;
            font-size: 13px;
            color: #e0e0e0;
            text-transform: none;
        }

        .actions {
            display: flex;
            gap: 15px;
            justify-content: flex-end;
            padding: 20px 0;
        }

        .toast {
            position: fixed;
            bottom: 30px;
            right: 30px;
            padding: 15px 25px;
            border-radius: 8px;
            font-weight: 600;
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s;
            z-index: 1000;
        }
        .toast.success {
            background: #10b981;
            color: white;
        }
        .toast.error {
            background: #f87171;
            color: white;
        }
        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        .filename-input {
            display: flex;
            gap: 5px;
            align-items: center;
        }
        .filename-input input {
            flex: 1;
        }
        .filename-input .suffix {
            color: #6b7280;
            font-size: 14px;
        }

        .config-type-badge {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            text-transform: uppercase;
            font-weight: 600;
        }
        .config-type-badge.spot { background: #10b981; color: white; }
        .config-type-badge.perp { background: #f59e0b; color: white; }
        .config-type-badge.grid { background: #8b5cf6; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>{{ "New Config" if is_new else "Edit Config" }}</h1>
                <a href="/config" class="back-link">&larr; Back to Config Manager</a>
            </div>
            <span class="config-type-badge {{ config_type }}">{{ config_type }}</span>
        </div>

        <form id="configForm">
            <!-- Filename (for new configs) -->
            {% if is_new %}
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">1</span>
                    File Settings
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label>Filename</label>
                        <div class="filename-input">
                            <input type="text" id="filename" placeholder="my_market_config" required pattern="[a-zA-Z0-9_-]+">
                            <span class="suffix">.json</span>
                        </div>
                        <span class="help-text">Letters, numbers, underscores, hyphens only</span>
                    </div>
                </div>
            </div>
            {% endif %}

            <!-- Market Identification -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}2{% else %}1{% endif %}</span>
                    Market Identification
                </div>
                <div class="form-grid">
                    {% if config_type == 'spot' %}
                    <div class="form-group">
                        <label>Trading Pair</label>
                        <input type="text" id="pair" value="{{ config.get('pair', '') }}" placeholder="XMR1/USDC" required>
                        <span class="help-text">Format: BASE/QUOTE (e.g., XMR1/USDC, PURR/USDC)</span>
                    </div>
                    {% else %}
                    <div class="form-group">
                        <label>Market</label>
                        <input type="text" id="market" value="{{ config.get('market', '') }}" placeholder="ICP" required>
                        <span class="help-text">For HIP-3: xyz:COPPER format</span>
                    </div>
                    <div class="form-group">
                        <label>DEX</label>
                        <input type="text" id="dex" value="{{ config.get('dex', '') }}" placeholder="">
                        <span class="help-text">Leave empty for canonical, or "xyz"/"flx" for builder markets</span>
                    </div>
                    {% endif %}
                    <div class="form-group full-width">
                        <label>Description</label>
                        <input type="text" id="description" value="{{ config.get('description', '') }}" placeholder="My trading bot config">
                    </div>
                </div>
            </div>

            <!-- Trading Parameters -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}3{% else %}2{% endif %}</span>
                    Trading Parameters
                </div>
                <div class="form-grid">
                    {% if config_type == 'grid' %}
                    <!-- Grid-specific trading params -->
                    <div class="form-group">
                        <label>Grid Spacing %</label>
                        <input type="number" id="grid_spacing_pct" value="{{ config.get('grid', {}).get('spacing_pct', 0.5) }}" step="0.1" min="0.1">
                        <span class="help-text">Percentage between grid levels</span>
                    </div>
                    <div class="form-group">
                        <label>Levels Each Side</label>
                        <input type="number" id="grid_num_levels" value="{{ config.get('grid', {}).get('num_levels_each_side', 5) }}" min="1" max="20">
                        <span class="help-text">Number of orders above/below price</span>
                    </div>
                    <div class="form-group">
                        <label>Order Size (USD)</label>
                        <input type="number" id="grid_order_size" value="{{ config.get('grid', {}).get('order_size_usd', 25) }}" step="1" min="1">
                    </div>
                    <div class="form-group">
                        <label>Rebalance Threshold %</label>
                        <input type="number" id="grid_rebalance" value="{{ config.get('grid', {}).get('rebalance_threshold_pct', 2.0) }}" step="0.5">
                        <span class="help-text">Rebalance grid when price moves this much</span>
                    </div>
                    <div class="form-group">
                        <label>Bias</label>
                        <select id="grid_bias">
                            <option value="neutral" {% if config.get('grid', {}).get('bias') == 'neutral' %}selected{% endif %}>Neutral</option>
                            <option value="long" {% if config.get('grid', {}).get('bias') == 'long' %}selected{% endif %}>Long</option>
                            <option value="short" {% if config.get('grid', {}).get('bias') == 'short' %}selected{% endif %}>Short</option>
                        </select>
                        <span class="help-text">Directional skew</span>
                    </div>
                    {% else %}
                    <!-- MM trading params (spot & perp) -->
                    <div class="form-group">
                        <label>Base Order Size{% if config_type == 'perp' %} (USD){% endif %}</label>
                        <input type="number" id="base_order_size" value="{{ config.get('trading', {}).get('base_order_size', 0.1) }}" step="0.01" min="0.01">
                        <span class="help-text">{% if config_type == 'perp' %}USD notional per order{% else %}Base token amount{% endif %}</span>
                    </div>
                    <div class="form-group">
                        <label>Min Order Size</label>
                        <input type="number" id="min_order_size" value="{{ config.get('trading', {}).get('min_order_size', 0.05) }}" step="0.01" min="0.01">
                    </div>
                    <div class="form-group">
                        <label>Base Spread (bps)</label>
                        <input type="number" id="base_spread_bps" value="{{ config.get('trading', {}).get('base_spread_bps', 35) }}" min="1">
                        <span class="help-text">1 bps = 0.01%</span>
                    </div>
                    <div class="form-group">
                        <label>Min Spread (bps)</label>
                        <input type="number" id="min_spread_bps" value="{{ config.get('trading', {}).get('min_spread_bps', 20) }}" min="1">
                    </div>
                    <div class="form-group">
                        <label>Max Spread (bps)</label>
                        <input type="number" id="max_spread_bps" value="{{ config.get('trading', {}).get('max_spread_bps', 100) }}" min="1">
                    </div>
                    <div class="form-group">
                        <label>Size Increment</label>
                        <input type="number" id="size_increment" value="{{ config.get('trading', {}).get('size_increment', 0.01) }}" step="0.001" min="0.001">
                    </div>
                    {% endif %}
                </div>
            </div>

            <!-- Position Limits -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}4{% else %}3{% endif %}</span>
                    Position Limits
                </div>
                <div class="form-grid">
                    {% if config_type == 'spot' %}
                    <div class="form-group">
                        <label>Target Position</label>
                        <input type="number" id="target_position" value="{{ config.get('position', {}).get('target_position', 0) }}" step="0.01">
                        <span class="help-text">Ideal position to hold (0 = neutral)</span>
                    </div>
                    <div class="form-group">
                        <label>Max Position Size</label>
                        <input type="number" id="max_position_size" value="{{ config.get('position', {}).get('max_position_size', 1.0) }}" step="0.1" min="0.1">
                        <span class="help-text">Maximum position in base token</span>
                    </div>
                    {% else %}
                    <div class="form-group">
                        <label>Target Position (USD)</label>
                        <input type="number" id="target_position_usd" value="{{ config.get('position', {}).get('target_position_usd', 0) }}" step="1">
                        <span class="help-text">Ideal position in USD (0 = neutral)</span>
                    </div>
                    <div class="form-group">
                        <label>Max Position (USD)</label>
                        <input type="number" id="max_position_usd" value="{{ config.get('position', {}).get('max_position_usd', 100) }}" step="10" min="10">
                    </div>
                    <div class="form-group">
                        <label>Leverage</label>
                        <input type="number" id="leverage" value="{{ config.get('position', {}).get('leverage', 3) }}" min="1" max="50">
                    </div>
                    {% endif %}
                </div>
            </div>

            <!-- Timing -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}5{% else %}4{% endif %}</span>
                    Timing
                </div>
                <div class="form-grid">
                    {% if config_type == 'grid' %}
                    <div class="form-group">
                        <label>Fill Check Interval (sec)</label>
                        <input type="number" id="fill_check_seconds" value="{{ config.get('timing', {}).get('fill_check_seconds', 5) }}" min="1">
                    </div>
                    <div class="form-group">
                        <label>Health Check Interval (sec)</label>
                        <input type="number" id="health_check_seconds" value="{{ config.get('timing', {}).get('health_check_seconds', 60) }}" min="10">
                    </div>
                    {% else %}
                    <div class="form-group">
                        <label>Update Threshold (bps)</label>
                        <input type="number" id="update_threshold_bps" value="{{ config.get('timing', {}).get('update_threshold_bps', 10) }}" min="1">
                        <span class="help-text">Re-quote when price moves this much</span>
                    </div>
                    <div class="form-group">
                        <label>Fallback Check (sec)</label>
                        <input type="number" id="fallback_check_seconds" value="{{ config.get('timing', {}).get('fallback_check_seconds', 30) }}" min="5">
                        <span class="help-text">Check even without price move</span>
                    </div>
                    {% if config_type == 'spot' %}
                    <div class="form-group">
                        <label>Update Interval (sec)</label>
                        <input type="number" id="update_interval_seconds" value="{{ config.get('timing', {}).get('update_interval_seconds', 5) }}" min="1">
                    </div>
                    {% endif %}
                    {% endif %}
                </div>
            </div>

            {% if config_type != 'grid' %}
            <!-- Inventory Management (MM only) -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}6{% else %}5{% endif %}</span>
                    Inventory Management
                </div>
                <div class="form-grid">
                    {% if config_type == 'spot' %}
                    <div class="form-group">
                        <label>Skew Threshold</label>
                        <input type="number" id="inventory_skew_threshold" value="{{ config.get('inventory', {}).get('inventory_skew_threshold', 0.1) }}" step="0.01">
                        <span class="help-text">Dead zone - no skew below this</span>
                    </div>
                    <div class="form-group">
                        <label>Skew BPS per Unit</label>
                        <input type="number" id="inventory_skew_bps_per_unit" value="{{ config.get('inventory', {}).get('inventory_skew_bps_per_unit', 25) }}" min="0">
                        <span class="help-text">How much to skew per unit of inventory</span>
                    </div>
                    {% else %}
                    <div class="form-group">
                        <label>Skew Threshold (USD)</label>
                        <input type="number" id="inventory_skew_threshold_usd" value="{{ config.get('inventory', {}).get('inventory_skew_threshold_usd', 25) }}" step="5">
                    </div>
                    <div class="form-group">
                        <label>Skew BPS per $1000</label>
                        <input type="number" id="inventory_skew_bps_per_1k" value="{{ config.get('inventory', {}).get('inventory_skew_bps_per_1k', 20) }}" min="0">
                    </div>
                    {% endif %}
                    <div class="form-group">
                        <label>Max Skew (bps)</label>
                        <input type="number" id="max_skew_bps" value="{{ config.get('inventory', {}).get('max_skew_bps', 80) }}" min="0">
                        <span class="help-text">Cap on inventory-based skew</span>
                    </div>
                </div>
            </div>
            {% endif %}

            {% if config_type == 'spot' %}
            <!-- Oracle Settings (Spot only) -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}7{% else %}6{% endif %}</span>
                    Oracle Settings
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label>Max Oracle Age (sec)</label>
                        <input type="number" id="max_oracle_age_seconds" value="{{ config.get('oracle', {}).get('max_oracle_age_seconds', 60) }}" min="5">
                        <span class="help-text">Reject stale oracle prices</span>
                    </div>
                    <div class="form-group">
                        <label>Max Oracle Jump %</label>
                        <input type="number" id="max_oracle_jump_pct" value="{{ config.get('oracle', {}).get('max_oracle_jump_pct', 5.0) }}" step="0.5">
                        <span class="help-text">Reject suspicious price moves</span>
                    </div>
                    <div class="form-group">
                        <label>Min Spread to Oracle (bps)</label>
                        <input type="number" id="min_spread_to_oracle_bps" value="{{ config.get('oracle', {}).get('min_spread_to_oracle_bps', 5) }}" min="0">
                    </div>
                </div>
            </div>
            {% endif %}

            {% if config_type == 'perp' %}
            <!-- Funding Settings (Perp only) -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}7{% else %}6{% endif %}</span>
                    Funding Rate
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label>Max Funding Rate % (8h)</label>
                        <input type="number" id="max_funding_rate_pct_8h" value="{{ config.get('funding', {}).get('max_funding_rate_pct_8h', 0.3) }}" step="0.05">
                        <span class="help-text">Stop trading if funding exceeds this</span>
                    </div>
                    <div class="form-group">
                        <label>Funding Skew Multiplier</label>
                        <input type="number" id="funding_skew_multiplier" value="{{ config.get('funding', {}).get('funding_skew_multiplier', 150) }}" min="0">
                        <span class="help-text">Skew quotes to avoid paying funding</span>
                    </div>
                </div>
            </div>

            <!-- Profit Taking (Perp only) -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">{% if is_new %}8{% else %}7{% endif %}</span>
                    Profit Taking
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label>Threshold (USD)</label>
                        <input type="number" id="profit_threshold_usd" value="{{ config.get('profit_taking', {}).get('threshold_usd', 2.0) }}" step="0.5">
                        <span class="help-text">Tighten spread when profit exceeds this</span>
                    </div>
                    <div class="form-group">
                        <label>Aggression (bps)</label>
                        <input type="number" id="profit_aggression_bps" value="{{ config.get('profit_taking', {}).get('aggression_bps', 10.0) }}" step="1">
                        <span class="help-text">How much to tighten spread</span>
                    </div>
                </div>
            </div>
            {% endif %}

            <!-- Safety Settings -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">S</span>
                    Safety
                </div>
                <div class="form-grid">
                    {% if config_type == 'grid' %}
                    <div class="form-group">
                        <label>Max Open Orders</label>
                        <input type="number" id="max_open_orders" value="{{ config.get('safety', {}).get('max_open_orders', 12) }}" min="2">
                    </div>
                    <div class="form-group">
                        <label>Emergency Stop Loss %</label>
                        <input type="number" id="emergency_stop_loss_pct" value="{{ config.get('safety', {}).get('emergency_stop_loss_pct', -15.0) }}" max="0">
                    </div>
                    <div class="form-group">
                        <label>Min Margin Ratio %</label>
                        <input type="number" id="min_margin_ratio_pct" value="{{ config.get('safety', {}).get('min_margin_ratio_pct', 10.0) }}" min="5">
                    </div>
                    <div class="form-group">
                        <label>Volatility Threshold %</label>
                        <input type="number" id="volatility_threshold_pct" value="{{ config.get('safety', {}).get('volatility_threshold_pct', 5.0) }}" step="0.5">
                    </div>
                    <div class="form-group">
                        <label>Max Account Drawdown %</label>
                        <input type="number" id="max_account_drawdown_pct" value="{{ config.get('safety', {}).get('max_account_drawdown_pct', -20.0) }}" max="0">
                    </div>
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="pause_on_high_volatility" {% if config.get('safety', {}).get('pause_on_high_volatility', True) %}checked{% endif %}>
                            <label for="pause_on_high_volatility">Pause on High Volatility</label>
                        </div>
                    </div>
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="close_position_on_emergency" {% if config.get('safety', {}).get('close_position_on_emergency', True) %}checked{% endif %}>
                            <label for="close_position_on_emergency">Close Position on Emergency</label>
                        </div>
                    </div>
                    {% else %}
                    <div class="form-group">
                        <label>Max Quote Count</label>
                        <input type="number" id="max_quote_count" value="{{ config.get('safety', {}).get('max_quote_count', 2) }}" min="1" max="10">
                        <span class="help-text">Max simultaneous orders per side</span>
                    </div>
                    <div class="form-group">
                        <label>Emergency Stop Loss %</label>
                        <input type="number" id="emergency_stop_loss_pct" value="{{ config.get('safety', {}).get('emergency_stop_loss_pct', -10.0) }}" max="0">
                    </div>
                    {% if config_type == 'spot' %}
                    <div class="form-group">
                        <label>Max Spot-Perp Deviation %</label>
                        <input type="number" id="max_spot_perp_deviation_pct" value="{{ config.get('safety', {}).get('max_spot_perp_deviation_pct', 5.0) }}" step="0.5">
                    </div>
                    <div class="form-group">
                        <label>Emergency Sell Below Oracle %</label>
                        <input type="number" id="emergency_sell_if_below_oracle_pct" value="{{ config.get('safety', {}).get('emergency_sell_if_below_oracle_pct', 15.0) }}" step="1">
                    </div>
                    {% else %}
                    <div class="form-group">
                        <label>Min Margin Ratio %</label>
                        <input type="number" id="min_margin_ratio_pct" value="{{ config.get('safety', {}).get('min_margin_ratio_pct', 20.0) }}" min="5">
                        <span class="help-text">Liquidation protection</span>
                    </div>
                    {% endif %}
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="smart_order_mgmt_enabled" {% if config.get('safety', {}).get('smart_order_mgmt_enabled', True) %}checked{% endif %}>
                            <label for="smart_order_mgmt_enabled">Smart Order Management</label>
                        </div>
                        <span class="help-text">Reduce unnecessary cancels/replaces</span>
                    </div>
                    {% endif %}
                </div>
            </div>

            <!-- Exchange Settings -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">X</span>
                    Exchange
                </div>
                <div class="form-grid">
                    {% if config_type == 'spot' %}
                    <div class="form-group">
                        <label>Spot Coin</label>
                        <input type="text" id="spot_coin" value="{{ config.get('exchange', {}).get('spot_coin', '') }}" placeholder="@260 or PURR/USDC">
                        <span class="help-text">@XXX for builder assets, PAIR/QUOTE for canonical</span>
                    </div>
                    <div class="form-group">
                        <label>Spot Coin (Order)</label>
                        <input type="text" id="spot_coin_order" value="{{ config.get('exchange', {}).get('spot_coin_order', '') }}" placeholder="@260 or PURR/USDC">
                        <span class="help-text">Usually same as spot_coin</span>
                    </div>
                    <div class="form-group">
                        <label>Perp Coin (Oracle)</label>
                        <input type="text" id="perp_coin" value="{{ config.get('exchange', {}).get('perp_coin', '') }}" placeholder="XMR">
                        <span class="help-text">Perp market for price oracle</span>
                    </div>
                    <div class="form-group">
                        <label>Perp DEX</label>
                        <input type="text" id="perp_dex" value="{{ config.get('exchange', {}).get('perp_dex', '') }}" placeholder="">
                        <span class="help-text">Leave empty for canonical perps</span>
                    </div>
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="use_perp_oracle_price" {% if config.get('exchange', {}).get('use_perp_oracle_price', False) %}checked{% endif %}>
                            <label for="use_perp_oracle_price">Use Perp Oracle Price</label>
                        </div>
                    </div>
                    {% endif %}
                    <div class="form-group">
                        <label>Price Decimals</label>
                        <input type="number" id="price_decimals" value="{{ config.get('exchange', {}).get('price_decimals', 2) }}" min="0" max="8">
                    </div>
                    <div class="form-group">
                        <label>Size Decimals</label>
                        <input type="number" id="size_decimals" value="{{ config.get('exchange', {}).get('size_decimals', 2) }}" min="0" max="8">
                    </div>
                </div>
            </div>

            <!-- Account Settings -->
            <div class="form-section">
                <div class="section-title">
                    <span class="section-icon">A</span>
                    Account
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label>Subaccount Address</label>
                        <input type="text" id="subaccount_address" value="{{ config.get('account', {}).get('subaccount_address') or '' }}" placeholder="0x...">
                        <span class="help-text">Leave empty to use main account</span>
                    </div>
                    <div class="form-group">
                        <div class="checkbox-group">
                            <input type="checkbox" id="is_subaccount" {% if config.get('account', {}).get('is_subaccount', False) %}checked{% endif %}>
                            <label for="is_subaccount">Is Subaccount</label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Actions -->
            <div class="actions">
                <a href="/config" class="btn btn-secondary">Cancel</a>
                <button type="submit" class="btn btn-primary">Save Config</button>
            </div>
        </form>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        const configType = '{{ config_type }}';
        const isNew = {{ 'true' if is_new else 'false' }};
        const originalFilename = '{{ filename }}';

        function showToast(message, type = 'success') {
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type + ' show';
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        function buildConfig() {
            const config = {};

            // Market identification
            if (configType === 'spot') {
                config.pair = document.getElementById('pair').value;
            } else {
                config.market = document.getElementById('market').value;
                config.dex = document.getElementById('dex').value;
            }
            config.description = document.getElementById('description').value;

            // Trading params
            if (configType === 'grid') {
                config.grid = {
                    spacing_pct: parseFloat(document.getElementById('grid_spacing_pct').value),
                    num_levels_each_side: parseInt(document.getElementById('grid_num_levels').value),
                    order_size_usd: parseFloat(document.getElementById('grid_order_size').value),
                    rebalance_threshold_pct: parseFloat(document.getElementById('grid_rebalance').value),
                    bias: document.getElementById('grid_bias').value
                };
            } else {
                config.trading = {
                    base_order_size: parseFloat(document.getElementById('base_order_size').value),
                    min_order_size: parseFloat(document.getElementById('min_order_size').value),
                    size_increment: parseFloat(document.getElementById('size_increment').value),
                    base_spread_bps: parseInt(document.getElementById('base_spread_bps').value),
                    min_spread_bps: parseInt(document.getElementById('min_spread_bps').value),
                    max_spread_bps: parseInt(document.getElementById('max_spread_bps').value)
                };
            }

            // Position limits
            config.position = {};
            if (configType === 'spot') {
                config.position.target_position = parseFloat(document.getElementById('target_position').value);
                config.position.max_position_size = parseFloat(document.getElementById('max_position_size').value);
            } else {
                config.position.target_position_usd = parseFloat(document.getElementById('target_position_usd').value);
                config.position.max_position_usd = parseFloat(document.getElementById('max_position_usd').value);
                config.position.leverage = parseInt(document.getElementById('leverage').value);
            }

            // Timing
            config.timing = {};
            if (configType === 'grid') {
                config.timing.fill_check_seconds = parseInt(document.getElementById('fill_check_seconds').value);
                config.timing.health_check_seconds = parseInt(document.getElementById('health_check_seconds').value);
            } else {
                config.timing.update_threshold_bps = parseInt(document.getElementById('update_threshold_bps').value);
                config.timing.fallback_check_seconds = parseInt(document.getElementById('fallback_check_seconds').value);
                if (configType === 'spot') {
                    config.timing.update_interval_seconds = parseInt(document.getElementById('update_interval_seconds').value);
                }
            }

            // Inventory (MM only)
            if (configType !== 'grid') {
                config.inventory = {};
                if (configType === 'spot') {
                    config.inventory.inventory_skew_threshold = parseFloat(document.getElementById('inventory_skew_threshold').value);
                    config.inventory.inventory_skew_bps_per_unit = parseInt(document.getElementById('inventory_skew_bps_per_unit').value);
                } else {
                    config.inventory.inventory_skew_threshold_usd = parseFloat(document.getElementById('inventory_skew_threshold_usd').value);
                    config.inventory.inventory_skew_bps_per_1k = parseInt(document.getElementById('inventory_skew_bps_per_1k').value);
                }
                config.inventory.max_skew_bps = parseInt(document.getElementById('max_skew_bps').value);
            }

            // Oracle (spot only)
            if (configType === 'spot') {
                config.oracle = {
                    max_oracle_age_seconds: parseInt(document.getElementById('max_oracle_age_seconds').value),
                    max_oracle_jump_pct: parseFloat(document.getElementById('max_oracle_jump_pct').value),
                    min_spread_to_oracle_bps: parseInt(document.getElementById('min_spread_to_oracle_bps').value)
                };
            }

            // Funding (perp only)
            if (configType === 'perp') {
                config.funding = {
                    max_funding_rate_pct_8h: parseFloat(document.getElementById('max_funding_rate_pct_8h').value),
                    funding_skew_multiplier: parseInt(document.getElementById('funding_skew_multiplier').value)
                };
                config.profit_taking = {
                    threshold_usd: parseFloat(document.getElementById('profit_threshold_usd').value),
                    aggression_bps: parseFloat(document.getElementById('profit_aggression_bps').value)
                };
            }

            // Safety
            config.safety = {};
            if (configType === 'grid') {
                config.safety.max_open_orders = parseInt(document.getElementById('max_open_orders').value);
                config.safety.emergency_stop_loss_pct = parseFloat(document.getElementById('emergency_stop_loss_pct').value);
                config.safety.min_margin_ratio_pct = parseFloat(document.getElementById('min_margin_ratio_pct').value);
                config.safety.volatility_threshold_pct = parseFloat(document.getElementById('volatility_threshold_pct').value);
                config.safety.max_account_drawdown_pct = parseFloat(document.getElementById('max_account_drawdown_pct').value);
                config.safety.pause_on_high_volatility = document.getElementById('pause_on_high_volatility').checked;
                config.safety.close_position_on_emergency = document.getElementById('close_position_on_emergency').checked;
            } else {
                config.safety.max_quote_count = parseInt(document.getElementById('max_quote_count').value);
                config.safety.emergency_stop_loss_pct = parseFloat(document.getElementById('emergency_stop_loss_pct').value);
                config.safety.smart_order_mgmt_enabled = document.getElementById('smart_order_mgmt_enabled').checked;
                if (configType === 'spot') {
                    config.safety.max_spot_perp_deviation_pct = parseFloat(document.getElementById('max_spot_perp_deviation_pct').value);
                    config.safety.emergency_sell_if_below_oracle_pct = parseFloat(document.getElementById('emergency_sell_if_below_oracle_pct').value);
                } else {
                    config.safety.min_margin_ratio_pct = parseFloat(document.getElementById('min_margin_ratio_pct').value);
                }
            }

            // Exchange
            config.exchange = {
                price_decimals: parseInt(document.getElementById('price_decimals').value),
                size_decimals: parseInt(document.getElementById('size_decimals').value)
            };
            if (configType === 'spot') {
                config.exchange.spot_coin = document.getElementById('spot_coin').value;
                config.exchange.spot_coin_order = document.getElementById('spot_coin_order').value;
                config.exchange.perp_coin = document.getElementById('perp_coin').value;
                config.exchange.perp_dex = document.getElementById('perp_dex').value;
                config.exchange.use_perp_oracle_price = document.getElementById('use_perp_oracle_price').checked;
            }

            // Account
            const subAddr = document.getElementById('subaccount_address').value.trim();
            config.account = {
                subaccount_address: subAddr || null,
                is_subaccount: document.getElementById('is_subaccount').checked
            };

            return config;
        }

        document.getElementById('configForm').onsubmit = async (e) => {
            e.preventDefault();

            const config = buildConfig();
            let filename = isNew ? document.getElementById('filename').value : originalFilename;

            try {
                const resp = await fetch('/config/api/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        filename: filename,
                        config: config,
                        is_new: isNew
                    })
                });

                const data = await resp.json();

                if (data.success) {
                    showToast('Config saved successfully!', 'success');
                    // Redirect to config list after short delay
                    setTimeout(() => window.location.href = '/config', 1500);
                } else {
                    showToast('Error: ' + data.error, 'error');
                }
            } catch (err) {
                showToast('Error saving config: ' + err.message, 'error');
            }
        };
    </script>

    <!-- Footer + AI Chat injected automatically by after_request -->
</body>
</html>
'''
