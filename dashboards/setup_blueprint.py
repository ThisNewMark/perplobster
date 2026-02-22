"""
Setup Blueprint - Wallet Connect & API Wallet Generation
Handles first-time onboarding: connect browser wallet, approve builder fee,
generate API wallet, and save credentials to .env.

Routes:
    GET  /setup                     - Setup wizard page
    GET  /setup/api/check-credentials - Check if credentials are configured
    POST /setup/api/post-action     - CORS proxy to Hyperliquid exchange API
    POST /setup/api/save-credentials - Save credentials to .env
"""

import os
import sys
import requests
from flask import Blueprint, render_template_string, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

setup_bp = Blueprint('setup', __name__, url_prefix='/setup')


# ============================================================================
# API ROUTES
# ============================================================================

@setup_bp.route('/api/check-credentials')
def check_credentials():
    """Check if .env has valid Hyperliquid credentials configured."""
    from credentials import needs_setup, get_credentials
    if needs_setup():
        return jsonify({'has_credentials': False, 'account_address': ''})

    creds = get_credentials()
    addr = creds.get('account_address', '')
    masked = addr[:6] + '...' + addr[-4:] if len(addr) > 10 else addr
    return jsonify({'has_credentials': True, 'account_address': masked})


@setup_bp.route('/api/post-action', methods=['POST'])
def post_action():
    """Proxy signed EIP-712 actions to Hyperliquid exchange API.
    Browser can't POST directly to api.hyperliquid.xyz due to CORS,
    so we forward the already-signed payload and return the response.
    """
    payload = request.json
    if not payload:
        return jsonify({'error': 'No payload provided'}), 400

    for field in ['action', 'nonce', 'signature']:
        if field not in payload:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    try:
        resp = requests.post(
            'https://api.hyperliquid.xyz/exchange',
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        return jsonify(resp.json()), resp.status_code
    except requests.Timeout:
        return jsonify({'error': 'Hyperliquid API timeout'}), 504
    except Exception as e:
        return jsonify({'error': f'Proxy error: {str(e)}'}), 502


@setup_bp.route('/api/save-credentials', methods=['POST'])
def save_credentials():
    """Save main wallet address and API wallet private key to .env,
    then initialize the trading database if needed.
    """
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    account_address = data.get('account_address', '').strip()
    secret_key = data.get('secret_key', '').strip()

    # Validate address
    if not account_address or not account_address.startswith('0x') or len(account_address) != 42:
        return jsonify({'error': 'Invalid account address (expected 0x + 40 hex chars)'}), 400

    # Validate key (64 hex chars, no 0x prefix)
    if secret_key.startswith('0x'):
        secret_key = secret_key[2:]
    if len(secret_key) != 64:
        return jsonify({'error': 'Invalid secret key (expected 64 hex chars)'}), 400
    try:
        int(secret_key, 16)
    except ValueError:
        return jsonify({'error': 'Secret key must be a hex string'}), 400

    from credentials import write_credentials_to_env, ensure_database_initialized
    try:
        write_credentials_to_env(account_address, secret_key)
        ensure_database_initialized()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Failed to save: {str(e)}'}), 500


# ============================================================================
# SETUP PAGE
# ============================================================================

SETUP_PAGE_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Perp Lobster - Setup</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ethers/6.13.4/ethers.umd.min.js" crossorigin="anonymous"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
            background: #0a0e27;
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .container {
            max-width: 640px;
            width: 100%;
            padding: 40px 20px;
        }

        .header {
            text-align: center;
            margin-bottom: 40px;
        }

        .header .logo {
            font-size: 48px;
            margin-bottom: 8px;
        }

        .header h1 {
            font-size: 24px;
            color: #00ffff;
            font-weight: 600;
        }

        .header p {
            color: #888;
            font-size: 13px;
            margin-top: 8px;
        }

        /* Progress bar */
        .progress {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 0;
            margin-bottom: 36px;
        }

        .progress-step {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .progress-circle {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            border: 2px solid #333;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: 600;
            color: #555;
            transition: all 0.3s ease;
        }

        .progress-circle.active {
            border-color: #00ffff;
            color: #00ffff;
            box-shadow: 0 0 12px rgba(0, 255, 255, 0.3);
        }

        .progress-circle.completed {
            border-color: #4ade80;
            background: #4ade80;
            color: #0a0e27;
        }

        .progress-label {
            font-size: 11px;
            color: #555;
            transition: color 0.3s;
        }

        .progress-label.active { color: #00ffff; }
        .progress-label.completed { color: #4ade80; }

        .progress-line {
            width: 40px;
            height: 2px;
            background: #333;
            margin: 0 8px;
            transition: background 0.3s;
        }

        .progress-line.completed { background: #4ade80; }

        /* Step cards */
        .card {
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(0, 255, 255, 0.15);
            border-radius: 12px;
            padding: 28px;
            margin-bottom: 20px;
            transition: all 0.3s ease;
        }

        .card.active {
            border-color: rgba(0, 255, 255, 0.4);
            box-shadow: 0 0 20px rgba(0, 255, 255, 0.08);
        }

        .card.completed {
            border-color: rgba(74, 222, 128, 0.3);
            opacity: 0.7;
        }

        .card h2 {
            font-size: 16px;
            color: #fff;
            margin-bottom: 8px;
        }

        .card p {
            font-size: 13px;
            color: #888;
            line-height: 1.5;
            margin-bottom: 16px;
        }

        .card .detail {
            font-size: 12px;
            color: #666;
            margin-top: 8px;
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-family: inherit;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn-primary {
            background: linear-gradient(135deg, #00aaaa, #008888);
            color: #fff;
        }

        .btn-primary:hover:not(:disabled) {
            background: linear-gradient(135deg, #00cccc, #00aaaa);
            box-shadow: 0 0 16px rgba(0, 255, 255, 0.3);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Status messages */
        .status {
            margin-top: 12px;
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 13px;
            display: none;
        }

        .status.error {
            display: block;
            background: rgba(248, 113, 113, 0.15);
            border: 1px solid rgba(248, 113, 113, 0.3);
            color: #f87171;
        }

        .status.success {
            display: block;
            background: rgba(74, 222, 128, 0.15);
            border: 1px solid rgba(74, 222, 128, 0.3);
            color: #4ade80;
        }

        .status.info {
            display: block;
            background: rgba(0, 255, 255, 0.1);
            border: 1px solid rgba(0, 255, 255, 0.2);
            color: #00cccc;
        }

        /* Wallet info */
        .wallet-info {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            background: rgba(0, 255, 255, 0.08);
            border: 1px solid rgba(0, 255, 255, 0.2);
            border-radius: 8px;
            font-size: 13px;
            color: #00ffff;
        }

        .wallet-info .dot {
            width: 8px;
            height: 8px;
            background: #4ade80;
            border-radius: 50%;
        }

        /* Spinner */
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-top-color: #fff;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        /* Success card */
        .success-card {
            text-align: center;
            padding: 40px 28px;
        }

        .success-card .checkmark {
            font-size: 48px;
            margin-bottom: 16px;
        }

        .success-card h2 {
            color: #4ade80;
            margin-bottom: 12px;
        }

        /* Already configured */
        .configured-card {
            text-align: center;
        }

        .configured-card .actions {
            display: flex;
            gap: 12px;
            justify-content: center;
            margin-top: 20px;
        }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.1);
            color: #ccc;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }

        .btn-secondary:hover { background: rgba(255, 255, 255, 0.15); }

        /* Hidden */
        [hidden] { display: none !important; }

        /* Fee detail */
        .fee-info {
            font-size: 12px;
            color: #666;
            background: rgba(255, 255, 255, 0.03);
            padding: 10px 14px;
            border-radius: 6px;
            margin-bottom: 16px;
            line-height: 1.6;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="logo">&#x1F99E;</div>
            <h1>Perp Lobster Setup</h1>
            <p>Connect your wallet to start trading on Hyperliquid</p>
        </div>

        <!-- Already configured view -->
        <div id="configured" class="card configured-card" hidden>
            <h2>Already Configured</h2>
            <p>Wallet: <span id="configuredAddr" style="color: #00ffff;"></span></p>
            <div class="actions">
                <a href="/" class="btn btn-primary">Go to Dashboard</a>
                <button class="btn btn-secondary" onclick="startFreshSetup()">Reconfigure</button>
            </div>
        </div>

        <!-- Progress bar -->
        <div id="progressBar" class="progress">
            <div class="progress-step">
                <div class="progress-circle active" id="pc1">1</div>
                <span class="progress-label active" id="pl1">Connect</span>
            </div>
            <div class="progress-line" id="line1"></div>
            <div class="progress-step">
                <div class="progress-circle" id="pc2">2</div>
                <span class="progress-label" id="pl2">Approve Fee</span>
            </div>
            <div class="progress-line" id="line2"></div>
            <div class="progress-step">
                <div class="progress-circle" id="pc3">3</div>
                <span class="progress-label" id="pl3">API Wallet</span>
            </div>
        </div>

        <!-- Step 1: Connect Wallet -->
        <div id="step1" class="card active">
            <h2>1. Connect Your Wallet</h2>
            <p>Connect the browser wallet you use for Hyperliquid. Any EVM wallet works — MetaMask, Rabby, Phantom, Rainbow, Coinbase Wallet, etc.</p>
            <div id="noWallet" hidden>
                <div class="status error">No wallet detected. Install <a href="https://metamask.io" target="_blank" style="color:#f87171;">MetaMask</a> or <a href="https://rabby.io" target="_blank" style="color:#f87171;">Rabby</a> and refresh this page.</div>
            </div>
            <button id="connectBtn" class="btn btn-primary" onclick="connectWallet()">Connect Wallet</button>
            <div id="walletInfo" class="wallet-info" hidden>
                <div class="dot"></div>
                <span>Connected: <strong id="walletAddr"></strong></span>
            </div>
            <div id="step1Status" class="status"></div>
        </div>

        <!-- Step 2: Approve Builder Fee -->
        <div id="step2" class="card" hidden>
            <h2>2. Approve Builder Fee</h2>
            <p>One-time on-chain approval. Your wallet will ask you to sign a message — no transaction, no gas fee.</p>
            <div class="fee-info">
                Fee: 0.01% (1 basis point) per trade — the lowest tier possible.<br>
                Builder: <code style="color:#00cccc;">0xC8f0...9BbCfA</code><br>
                This supports the developer who builds and maintains Perp Lobster.
            </div>
            <button id="approveBtn" class="btn btn-primary" onclick="approveBuilderFee()">Approve Builder Fee</button>
            <div id="step2Status" class="status"></div>
        </div>

        <!-- Step 3: Generate API Wallet -->
        <div id="step3" class="card" hidden>
            <h2>3. Generate API Wallet</h2>
            <p>Creates a dedicated trading key so your main wallet stays safe. The API wallet can place trades but cannot withdraw funds. Your wallet will ask you to sign one more message to authorize it.</p>
            <button id="generateBtn" class="btn btn-primary" onclick="generateApiWallet()">Generate & Authorize API Wallet</button>
            <div id="step3Status" class="status"></div>
        </div>

        <!-- Success -->
        <div id="successCard" class="card success-card" hidden>
            <div class="checkmark">&#x2705;</div>
            <h2>Setup Complete!</h2>
            <p>Your credentials have been saved. Redirecting to the dashboard...</p>
        </div>
    </div>

<script>
// ============================================================
// CONSTANTS
// ============================================================

const BUILDER_ADDRESS = "0xC8f0cD137E28f717A20f810b46926f92978BbCfA";

// ============================================================
// STATE
// ============================================================

let connectedAddress = null;
let apiWalletPrivateKey = null;
let walletChainId = null;       // decimal int
let walletChainIdHex = null;    // hex string like "0x3e7"

// ============================================================
// EIP-712 DOMAIN (uses wallet's active chain — Hyperliquid accepts any chainId)
// ============================================================

function getHL_Domain() {
    return {
        name: "HyperliquidSignTransaction",
        version: "1",
        chainId: walletChainId,
        verifyingContract: "0x0000000000000000000000000000000000000000"
    };
}

// ============================================================
// INIT
// ============================================================

document.addEventListener('DOMContentLoaded', async () => {
    // Check if already configured
    try {
        const resp = await fetch('/setup/api/check-credentials');
        const data = await resp.json();
        if (data.has_credentials) {
            document.getElementById('configured').hidden = false;
            document.getElementById('configuredAddr').textContent = data.account_address;
            document.getElementById('progressBar').hidden = true;
            document.getElementById('step1').hidden = true;
            return;
        }
    } catch (e) {
        // Continue with setup
    }

    // Check wallet availability
    if (typeof window.ethereum === 'undefined') {
        document.getElementById('noWallet').hidden = false;
        document.getElementById('connectBtn').hidden = true;
    }

    // Check ethers.js loaded
    if (typeof ethers === 'undefined') {
        showStatus('step1', 'error', 'Failed to load ethers.js library. Check your internet connection and refresh.');
    }
});

// ============================================================
// STEP 1: CONNECT WALLET
// ============================================================

async function connectWallet() {
    try {
        setLoading('connectBtn', 'Connecting...');

        const accounts = await window.ethereum.request({
            method: 'eth_requestAccounts'
        });
        connectedAddress = accounts[0];

        // Get the wallet's active chainId (Hyperliquid accepts any chain for signing)
        const chainHex = await window.ethereum.request({ method: 'eth_chainId' });
        walletChainIdHex = chainHex;
        walletChainId = parseInt(chainHex, 16);

        // Show connected address
        document.getElementById('connectBtn').hidden = true;
        document.getElementById('walletInfo').hidden = false;
        document.getElementById('walletAddr').textContent =
            connectedAddress.slice(0, 6) + '...' + connectedAddress.slice(-4);

        // Advance
        completeStep(1);
        activateStep(2);

    } catch (err) {
        resetBtn('connectBtn', 'Connect Wallet');
        if (err.code === 4001) {
            showStatus('step1', 'error', 'Connection rejected. Click to try again.');
        } else {
            showStatus('step1', 'error', 'Connection failed: ' + err.message);
        }
    }
}

// ============================================================
// STEP 2: APPROVE BUILDER FEE
// ============================================================

async function approveBuilderFee() {
    const nonce = Date.now();

    const typedData = {
        types: {
            EIP712Domain: [
                { name: "name", type: "string" },
                { name: "version", type: "string" },
                { name: "chainId", type: "uint256" },
                { name: "verifyingContract", type: "address" }
            ],
            "HyperliquidTransaction:ApproveBuilderFee": [
                { name: "hyperliquidChain", type: "string" },
                { name: "maxFeeRate", type: "string" },
                { name: "builder", type: "address" },
                { name: "nonce", type: "uint64" }
            ]
        },
        primaryType: "HyperliquidTransaction:ApproveBuilderFee",
        domain: getHL_Domain(),
        message: {
            hyperliquidChain: "Mainnet",
            maxFeeRate: "0.01%",
            builder: BUILDER_ADDRESS,
            nonce: nonce
        }
    };

    try {
        setLoading('approveBtn', 'Sign in wallet...');

        const sigHex = await window.ethereum.request({
            method: 'eth_signTypedData_v4',
            params: [connectedAddress, JSON.stringify(typedData)]
        });
        const sig = parseSignature(sigHex);

        setLoading('approveBtn', 'Submitting to Hyperliquid...');

        const payload = {
            action: {
                type: "approveBuilderFee",
                hyperliquidChain: "Mainnet",
                signatureChainId: walletChainIdHex,
                maxFeeRate: "0.01%",
                builder: BUILDER_ADDRESS,
                nonce: nonce
            },
            nonce: nonce,
            signature: sig,
            vaultAddress: null,
            expiresAfter: null
        };

        const resp = await fetch('/setup/api/post-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await resp.json();

        if (result.status === 'ok') {
            showStatus('step2', 'success', 'Builder fee approved!');
            completeStep(2);
            activateStep(3);
        } else {
            const msg = result.response || JSON.stringify(result);
            if (msg.toLowerCase().includes('already')) {
                showStatus('step2', 'success', 'Builder fee already approved!');
                completeStep(2);
                activateStep(3);
            } else {
                showStatus('step2', 'error', 'Approval failed: ' + msg);
                resetBtn('approveBtn', 'Approve Builder Fee');
            }
        }
    } catch (err) {
        resetBtn('approveBtn', 'Approve Builder Fee');
        if (err.code === 4001) {
            showStatus('step2', 'error', 'Signature rejected. Click to try again.');
        } else {
            showStatus('step2', 'error', 'Error: ' + err.message);
        }
    }
}

// ============================================================
// STEP 3: GENERATE API WALLET
// ============================================================

async function generateApiWallet() {
    try {
        setLoading('generateBtn', 'Generating keypair...');

        // Generate random wallet
        const randomWallet = ethers.Wallet.createRandom();
        apiWalletPrivateKey = randomWallet.privateKey.slice(2); // Remove 0x
        const apiWalletAddress = randomWallet.address;

        const nonce = Date.now();

        const typedData = {
            types: {
                EIP712Domain: [
                    { name: "name", type: "string" },
                    { name: "version", type: "string" },
                    { name: "chainId", type: "uint256" },
                    { name: "verifyingContract", type: "address" }
                ],
                "HyperliquidTransaction:ApproveAgent": [
                    { name: "hyperliquidChain", type: "string" },
                    { name: "agentAddress", type: "address" },
                    { name: "agentName", type: "string" },
                    { name: "nonce", type: "uint64" }
                ]
            },
            primaryType: "HyperliquidTransaction:ApproveAgent",
            domain: getHL_Domain(),
            message: {
                hyperliquidChain: "Mainnet",
                agentAddress: apiWalletAddress,
                agentName: "Perp Lobster Bot",
                nonce: nonce
            }
        };

        setLoading('generateBtn', 'Sign in wallet...');

        const sigHex = await window.ethereum.request({
            method: 'eth_signTypedData_v4',
            params: [connectedAddress, JSON.stringify(typedData)]
        });
        const sig = parseSignature(sigHex);

        setLoading('generateBtn', 'Registering on Hyperliquid...');

        const payload = {
            action: {
                type: "approveAgent",
                hyperliquidChain: "Mainnet",
                signatureChainId: walletChainIdHex,
                agentAddress: apiWalletAddress,
                agentName: "Perp Lobster Bot",
                nonce: nonce
            },
            nonce: nonce,
            signature: sig,
            vaultAddress: null,
            expiresAfter: null
        };

        const resp = await fetch('/setup/api/post-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await resp.json();

        if (result.status === 'ok') {
            setLoading('generateBtn', 'Saving credentials...');

            const saveResp = await fetch('/setup/api/save-credentials', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_address: connectedAddress,
                    secret_key: apiWalletPrivateKey
                })
            });
            const saveResult = await saveResp.json();

            // Clear sensitive data from memory immediately
            apiWalletPrivateKey = null;

            if (saveResult.success) {
                showStatus('step3', 'success', 'API wallet created and credentials saved!');
                completeStep(3);

                // Show success and redirect
                document.getElementById('step3').hidden = true;
                document.getElementById('successCard').hidden = false;
                setTimeout(() => { window.location.href = '/'; }, 2500);
            } else {
                showStatus('step3', 'error', 'Failed to save credentials: ' + saveResult.error);
                resetBtn('generateBtn', 'Generate & Authorize API Wallet');
            }
        } else {
            apiWalletPrivateKey = null;
            const msg = result.response || JSON.stringify(result);
            showStatus('step3', 'error', 'Agent approval failed: ' + msg);
            resetBtn('generateBtn', 'Generate & Authorize API Wallet');
        }
    } catch (err) {
        apiWalletPrivateKey = null;
        resetBtn('generateBtn', 'Generate & Authorize API Wallet');
        if (err.code === 4001) {
            showStatus('step3', 'error', 'Signature rejected. Click to try again.');
        } else {
            showStatus('step3', 'error', 'Error: ' + err.message);
        }
    }
}

// ============================================================
// UI HELPERS
// ============================================================

function parseSignature(sigHex) {
    const sig = sigHex.startsWith('0x') ? sigHex.slice(2) : sigHex;
    return {
        r: '0x' + sig.slice(0, 64),
        s: '0x' + sig.slice(64, 128),
        v: parseInt(sig.slice(128, 130), 16)
    };
}

function activateStep(n) {
    const card = document.getElementById('step' + n);
    if (card) {
        card.hidden = false;
        card.classList.add('active');
    }
    const circle = document.getElementById('pc' + n);
    const label = document.getElementById('pl' + n);
    if (circle) circle.classList.add('active');
    if (label) label.classList.add('active');
}

function completeStep(n) {
    const card = document.getElementById('step' + n);
    if (card) {
        card.classList.remove('active');
        card.classList.add('completed');
    }
    const circle = document.getElementById('pc' + n);
    const label = document.getElementById('pl' + n);
    if (circle) {
        circle.classList.remove('active');
        circle.classList.add('completed');
        circle.innerHTML = '&#x2713;';
    }
    if (label) {
        label.classList.remove('active');
        label.classList.add('completed');
    }
    const line = document.getElementById('line' + n);
    if (line) line.classList.add('completed');
}

function showStatus(stepId, type, msg) {
    const el = document.getElementById(stepId + 'Status');
    if (el) {
        el.className = 'status ' + type;
        el.textContent = msg;
    }
}

function setLoading(btnId, text) {
    const btn = document.getElementById(btnId);
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> ' + text;
}

function resetBtn(btnId, text) {
    const btn = document.getElementById(btnId);
    btn.disabled = false;
    btn.textContent = text;
}

function startFreshSetup() {
    document.getElementById('configured').hidden = true;
    document.getElementById('progressBar').hidden = false;
    document.getElementById('step1').hidden = false;

    if (typeof window.ethereum === 'undefined') {
        document.getElementById('noWallet').hidden = false;
        document.getElementById('connectBtn').hidden = true;
    }
}
</script>
</body>
</html>
"""


@setup_bp.route('/')
def setup_page():
    """Render the setup wizard page."""
    return render_template_string(SETUP_PAGE_TEMPLATE)
