# Glimpse Portal

Django admin portal for Glimpse App, connected to Supabase PostgreSQL database.

## Architecture

- **Main Site**: `glimpseapp.net` → WordPress (separate container via Traefik)
- **Admin Portal**: `glimpseapp.net/portal` → Django Admin (this project)
- **Routing**: Traefik (central reverse proxy)
- **Databases**:
  - Local PostgreSQL → Django internals (auth, sessions)
  - Supabase → Business models

## Quick Start

### 1. Setup Environment

```bash
cp .env.example .env
# Edit .env with your Supabase credentials and secret key
```

### 2. Local Development

```bash
# Install dependencies
poetry install

# Start local PostgreSQL
docker-compose up db -d

# Run migrations (Django tables)
poetry run python manage.py migrate

# Create superuser
poetry run python manage.py createsuperuser

# Generate models from Supabase
poetry run python manage.py generate_models --write

# Run development server
poetry run python manage.py runserver
```

Visit: http://localhost:8000/portal/

### 3. Docker Deployment (with Traefik)

Make sure Traefik network exists:
```bash
docker network create traefik_proxy
```

Deploy:
```bash
docker-compose up -d --build
```

## Generate Models from Supabase

```bash
# Preview models
poetry run python manage.py generate_models

# Write to portal/models.py
poetry run python manage.py generate_models --write

# With managed=True (Django manages migrations)
poetry run python manage.py generate_models --write --managed
```

## Project Structure

```
glimpse-portal/
├── config/
│   ├── settings.py      # Django settings
│   ├── urls.py          # URL routing
│   └── routers.py       # Database router
├── portal/              # Main app
│   ├── models.py        # Generated from Supabase
│   ├── admin.py         # Admin registrations
│   └── management/commands/
│       └── generate_models.py
├── docker-compose.yml   # Django + PostgreSQL + Traefik labels
├── Dockerfile
└── pyproject.toml
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | Debug mode (True/False) |
| `SITE_DOMAIN` | Domain for Traefik routing |
| `DJANGO_DB_*` | Local PostgreSQL for Django |
| `SUPABASE_DATABASE_URL` | Supabase connection string |

## Database Routing

- `portal` app → Supabase database
- Everything else → Local PostgreSQL

## Commands

```bash
poetry run python manage.py migrate                    # Migrate Django tables
poetry run python manage.py migrate --database=supabase  # Migrate Supabase (if managed)
poetry run python manage.py createsuperuser            # Create admin user
poetry run python manage.py generate_models --write    # Generate models from Supabase
poetry run python manage.py collectstatic              # Collect static files
```
