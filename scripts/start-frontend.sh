#!/bin/bash
# DeepOdds frontend start script.
# Run: setsid scripts/start-frontend.sh &>/tmp/frontend.log &
set -e
cd "$(dirname "$0")/../frontend"
exec npx vite --host 0.0.0.0 --port 5173
