#!/bin/bash
# ===========================================
# Perp Lobster - Start Bot
# ===========================================
# Usage: ./start.sh <config_file>
# Example: ./start.sh config/my_hype_grid.json
#
# Starts the bot in the background with logging.
# The bot type is auto-detected from the config file.

set -e

CONFIG_FILE="$1"

if [ -z "$CONFIG_FILE" ]; then
    echo "Usage: ./start.sh <config_file>"
    echo "Example: ./start.sh config/my_hype_grid.json"
    echo ""
    echo "Available configs:"
    ls config/*.json 2>/dev/null | grep -v examples || echo "  No configs found. Copy one from config/examples/"
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file not found: $CONFIG_FILE"
    exit 1
fi

# Auto-detect bot type from config
if grep -q '"grid"' "$CONFIG_FILE"; then
    BOT_SCRIPT="bots/grid_trader.py"
    BOT_TYPE="Grid Trader"
elif grep -q '"pair"' "$CONFIG_FILE" || grep -q '"spot_coin"' "$CONFIG_FILE"; then
    BOT_SCRIPT="bots/spot_market_maker.py"
    BOT_TYPE="Spot Market Maker"
else
    BOT_SCRIPT="bots/perp_market_maker.py"
    BOT_TYPE="Perp Market Maker"
fi

# Create logs directory
mkdir -p logs

# Generate log filename from config
LOG_NAME=$(basename "$CONFIG_FILE" .json)
LOG_FILE="logs/${LOG_NAME}.log"
PID_FILE="logs/${LOG_NAME}.pid"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Bot is already running (PID: $OLD_PID)"
        echo "Stop it first with: ./stop.sh $CONFIG_FILE"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# Activate venv
source venv/bin/activate

echo "Starting $BOT_TYPE..."
echo "  Config: $CONFIG_FILE"
echo "  Log: $LOG_FILE"

# Start bot in background
nohup python "$BOT_SCRIPT" --config "$CONFIG_FILE" > "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"

echo "  PID: $BOT_PID"
echo ""
echo "Bot started! View logs with:"
echo "  tail -f $LOG_FILE"
echo ""
echo "Stop with:"
echo "  ./stop.sh $CONFIG_FILE"
