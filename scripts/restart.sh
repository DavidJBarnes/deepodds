#!/bin/bash
# Restart both backend and frontend. Safe to run any time.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Killing old processes ==="
pkill -f "uvicorn app.main" 2>/dev/null || true
pkill -f "vite.*5173" 2>/dev/null || true
sleep 2

echo "=== Starting backend ==="
setsid "$DIR/scripts/start-backend.sh" &>/tmp/backend.log &
echo "  backend pid=$!"

echo "=== Starting frontend ==="
setsid "$DIR/scripts/start-frontend.sh" &>/tmp/frontend.log &
echo "  frontend pid=$!"

echo "=== Waiting for readiness ==="
for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "  backend OK"
    break
  fi
  sleep 1
done
for i in $(seq 1 20); do
  if curl -sf -o /dev/null http://localhost:5173 >/dev/null 2>&1; then
    echo "  frontend OK"
    break
  fi
  sleep 1
done

echo "=== Done ==="
