#!/bin/bash
# ===========================================
# Perp Lobster - Stop Bot
# ===========================================
# Usage: ./stop.sh <config_file>    - Stop a specific bot
#        ./stop.sh --all            - Stop all bots

set -e

if [ "$1" = "--all" ]; then
    echo "Stopping all Perp Lobster bots..."
    STOPPED=0
    for PID_FILE in logs/*.pid; do
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            NAME=$(basename "$PID_FILE" .pid)
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID"
                echo "  Stopped $NAME (PID: $PID)"
                STOPPED=$((STOPPED + 1))
            fi
            rm -f "$PID_FILE"
        fi
    done
    if [ $STOPPED -eq 0 ]; then
        echo "  No running bots found."
    else
        echo "Stopped $STOPPED bot(s)."
    fi
    exit 0
fi

CONFIG_FILE="$1"

if [ -z "$CONFIG_FILE" ]; then
    echo "Usage: ./stop.sh <config_file>"
    echo "       ./stop.sh --all"
    echo ""
    echo "Running bots:"
    for PID_FILE in logs/*.pid; do
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            NAME=$(basename "$PID_FILE" .pid)
            if kill -0 "$PID" 2>/dev/null; then
                echo "  $NAME (PID: $PID) - running"
            else
                echo "  $NAME (PID: $PID) - stale"
                rm -f "$PID_FILE"
            fi
        fi
    done
    exit 1
fi

LOG_NAME=$(basename "$CONFIG_FILE" .json)
PID_FILE="logs/${LOG_NAME}.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found for $CONFIG_FILE"
    echo "Bot may not be running."
    exit 1
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Stopped bot (PID: $PID)"
    rm -f "$PID_FILE"
else
    echo "Bot process $PID is not running (stale PID file)"
    rm -f "$PID_FILE"
fi
