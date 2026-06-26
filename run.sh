#!/bin/bash
set -e

echo "=== AI GF Bot ==="
echo "Starting at 06/27/2026 00:09:53"

# Check .env exists
if [ ! -f .env ]; then
    echo "[WARN] .env not found, creating from .env.example"
    cp .env.example .env
    echo "[WARN] Please edit .env with your real credentials!"
    exit 1
fi

# Create required directories
mkdir -p logs backups media

# Check Python
python3 --version

# Install deps if needed
if [ ! -d "venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv venv
fi
source venv/bin/activate

pip install -q -r requirements.txt

echo "Starting bot..."
exec python bot.py
