#!/bin/bash
# DeepOdds backend start script.
# Uses exec so the uvicorn process inherits the PID — no orphaned shells.
# Run: setsid scripts/start-backend.sh &>/tmp/backend.log &
set -e
cd "$(dirname "$0")/../backend"
PYTHONPATH=. exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
