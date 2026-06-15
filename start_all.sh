#!/bin/bash
# Manual Startup Script for Mumo Syntax & Capital
# Use this when systemctl --user is failing to connect to the bus.

# BASE_DIR should be the directory where the script is located
BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$BASE_DIR"
export PYTHONPATH=$BASE_DIR

echo "🚀 Starting Mumo Syntax & Capital System..."

# 1. Kill any existing processes (forceful) to start clean
echo "🧹 Cleaning up old processes..."
pkill -9 -f "signal_service.py"
pkill -9 -f "signal_tracker.py"
pkill -9 -f "admin_server.py"
pkill -9 -f "interactive_bot.py"
pkill -9 -f "mumo-syntax-capital"

sleep 2

# 2. Start all components in the background
echo "📡 Starting Signal Service..."
./venv/bin/python signal_service.py >> signals.log 2>&1 &

echo "🎯 Starting Signal Tracker..."
./venv/bin/python signal_tracker.py >> tracker.log 2>&1 &

echo "📊 Starting Admin Dashboard..."
./venv/bin/python admin_server.py >> admin.log 2>&1 &

echo "🤖 Starting Telegram Bot..."
./venv/bin/python app/interactive_bot.py >> bot.log 2>&1 &

echo "✅ All services started manually!"
echo "Use 'ps aux | grep python3' to verify or check the .log files."
