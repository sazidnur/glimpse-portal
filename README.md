# Glimpse Portal

Django admin portal for Glimpse App, backed by PostgreSQL and Redis.

## Architecture

- Main site: `glimpseapp.net` (WordPress, separate service)
- Admin portal: `glimpseapp.net/portal` (this Django project)
- Routing: Traefik in production
- Database: PostgreSQL for Django internals and business models
- Cache: Redis for API/cache acceleration

## Quick Start

### 1. Setup Environment

```bash
cp .env.example .env
# Edit .env with your database credentials and secret key
```

### 2. Local Development

```bash
# Install dependencies
poetry install

# Start local PostgreSQL
docker compose up db -d

# Run migrations
poetry run python manage.py migrate

# Create superuser
poetry run python manage.py createsuperuser

# Generate/sync models from current schema (optional)
poetry run python manage.py generate_models --write

# Run development server
poetry run python manage.py runserver
```

Visit: http://localhost:8000/portal/

### 3. Docker Deployment (Production)

Make sure Traefik network exists:

```bash
docker network create traefik_proxy
```

Deploy:

```bash
docker compose up -d --build
```

## Generate Models from Database Schema

```bash
# Preview models
poetry run python manage.py generate_models

# Write models
poetry run python manage.py generate_models --write

# Force sync/update models
poetry run python manage.py generate_models --write --force
```

## Project Structure

```text
glimpse-portal/
├── config/                  # Django project settings/urls
├── portal/                  # Main app
│   ├── models.py
│   ├── admin.py
│   └── management/commands/
├── api/                     # API views, serializers, cache layer
├── docker-compose.yml       # Production compose
├── docker-compose.dev.yml   # Standalone local dev compose
├── Dockerfile
└── pyproject.toml
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Debug mode (`True`/`False`) |
| `SITE_DOMAIN` | Domain for Traefik routing |
| `DJANGO_DB_*` | PostgreSQL connection settings |

## Common Commands

```bash
poetry run python manage.py migrate
poetry run python manage.py createsuperuser
poetry run python manage.py generate_models --write
poetry run python manage.py collectstatic
```
