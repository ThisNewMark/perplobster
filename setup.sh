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
    echo "  Created .env - YOU MUST EDIT THIS with your credentials!"
    echo ""
    echo "  Edit .env and set:"
    echo "    HL_ACCOUNT_ADDRESS=0xYourWalletAddress"
    echo "    HL_SECRET_KEY=your_private_key_hex"
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
echo "  1. Edit .env with your Hyperliquid credentials"
echo "  2. Create a config file (copy from config/examples/)"
echo "  3. Start a bot:"
echo "     python bots/perp_market_maker.py --config config/my_config.json"
echo "  4. Open the dashboard:"
echo "     python dashboards/dashboard.py"
echo "     Then visit http://localhost:5050"
echo "============================================"
echo ""
