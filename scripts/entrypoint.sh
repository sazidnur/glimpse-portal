#!/bin/bash
# ===========================================
# Entrypoint script for Django container
# ===========================================

set -e

echo "🚀 Starting Glimpse Portal..."

if [ "${SKIP_STARTUP_TASKS:-0}" != "1" ]; then
  echo "📦 Running migrations..."
  python manage.py migrate --database=default --noinput

  echo "📁 Collecting static files..."
  python manage.py collectstatic --noinput --clear

  echo "🔥 Warming Redis caches..."
  python manage.py warm_cache || echo "Cache warm failed, will lazy-warm on first request"
else
  echo "Skipping startup tasks (SKIP_STARTUP_TASKS=1)"
fi

echo "✅ Ready!"

# Execute the main command
exec "$@"