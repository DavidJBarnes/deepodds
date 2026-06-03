#!/bin/bash
set -e

python -m scanner.main &
SCANNER_PID=$!
echo "Scanner started (pid=$SCANNER_PID)"

cleanup() {
    echo "Shutting down scanner (pid=$SCANNER_PID)..."
    kill $SCANNER_PID 2>/dev/null || true
    wait $SCANNER_PID 2>/dev/null || true
    echo "Scanner stopped."
}
trap cleanup SIGTERM SIGINT

exec uvicorn app.main:app \
    --host 0.0.0.0 --port "${API_PORT:-8000}" \
    --proxy-headers --forwarded-allow-ips=*
