#!/bin/bash
# Keep Celery running — restarts if it crashes
cd "$(dirname "$0")"
rm -f celerybeat-schedule*
while true; do
    echo "[$(date)] Starting Celery worker+beat..."
    .venv/bin/celery -A app.celery_app worker --beat --loglevel=warning
    echo "[$(date)] Celery exited with code $?. Restarting in 3s..."
    sleep 3
done
