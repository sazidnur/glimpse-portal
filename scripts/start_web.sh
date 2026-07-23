#!/bin/bash
# Runs gunicorn and the live feed service side by side in the django
# container. The live feed service owns all hub WebSockets, so gunicorn
# workers can restart freely without dropping connections. If the service
# crashes it is restarted here; if gunicorn dies the container exits and
# Docker restarts everything.

set -e

GUNICORN_PID=""
SERVICE_LOOP_PID=""

shutdown() {
  kill -TERM "$GUNICORN_PID" 2>/dev/null || true
  kill -TERM "$SERVICE_LOOP_PID" 2>/dev/null || true
  pkill -TERM -f "manage.py live_feed_service" 2>/dev/null || true
}
trap shutdown TERM INT

run_service_loop() {
  while true; do
    python manage.py live_feed_service && break
    echo "live_feed_service exited unexpectedly; restarting in 3s..."
    sleep 3
  done
}

gunicorn --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-1}" config.wsgi:application &
GUNICORN_PID=$!

run_service_loop &
SERVICE_LOOP_PID=$!

wait "$GUNICORN_PID"
EXIT_CODE=$?

shutdown
wait 2>/dev/null || true
exit "$EXIT_CODE"
