#!/bin/bash
# ===========================================
# Entrypoint script for Django container
# ===========================================

set -e

echo "🚀 Starting Glimpse Portal..."

echo "📦 Running migrations..."
python manage.py migrate --database=default --noinput

# Collect static files
echo "📁 Collecting static files..."
python manage.py collectstatic --noinput --clear

# Warm Redis caches (non-blocking -- continues even if Redis is unavailable)
echo "🔥 Warming Redis caches..."
python manage.py warm_cache || echo "⚠️  Cache warm failed, will lazy-warm on first request"

echo "✅ Ready!"

# Execute the main command
exec "$@"
