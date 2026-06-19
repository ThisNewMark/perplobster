#!/bin/bash
# ===========================================
# Perp Lobster - Quick Setup Script
# ===========================================

set -e

echo ""
echo "  🦞 Perp Lobster - Hyperliquid Trading Bots"
echo "  ============================================"
echo ""

# Check Python version
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "ERROR: Python 3 is required but not found."
    echo "Install it from https://python.org or via your package manager."
    exit 1
fi

echo "Using: $($PYTHON --version)"
echo ""

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv venv
    echo "  Done."
else
    echo "Virtual environment already exists."
fi

# Activate venv
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt --quiet
echo "  Done."

# Create .env from example if it doesn't exist
if [ ! -f ".env" ]; then
    echo ""
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "  Created .env - credentials are configured in the browser via the setup wizard."
    echo "  (No need to edit this file by hand.)"
else
    echo ".env file already exists."
fi

# Initialize database
echo ""
echo "Initializing database..."
$PYTHON tools/init_db.py
echo ""

echo "============================================"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Start the dashboard:"
echo "       source venv/bin/activate && python dashboards/dashboard.py"
echo "  2. Open http://localhost:5050 in a browser with your wallet"
echo "     extension (MetaMask, Rabby, etc.). You'll be taken to the"
echo "     setup wizard to connect your wallet, approve the builder fee,"
echo "     and generate a trade-only API wallet. No keys to paste."
echo "  3. Create a config file (copy from config/examples/) to run a bot."
echo "============================================"
echo ""
