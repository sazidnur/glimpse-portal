"""
Django settings for Glimpse Portal.

This portal runs at glimpseapp.net/portal and serves as the admin interface.
Connected to Supabase PostgreSQL database.
"""

from pathlib import Path
from decouple import config, Csv
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# Portal URL prefix (e.g., 'portal' for glimpseapp.net/portal)
PORTAL_URL_PREFIX = config('PORTAL_URL_PREFIX', default='portal')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    
    # Local apps
    'supabase',
]

# Add debug toolbar in development
if DEBUG:
    INSTALLED_APPS += ['debug_toolbar']

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'config.middleware.APIIPWhitelistMiddleware',
]

# Add debug toolbar middleware in development
if DEBUG:
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ===========================================
# Database Configuration (Two Databases)
# ===========================================
# default  - Local PostgreSQL for Django internals (auth, sessions, admin)
# supabase - Supabase PostgreSQL for business models

SUPABASE_DATABASE_URL = config('SUPABASE_DATABASE_URL', default=None)

# Default database - Django internals (local PostgreSQL in Docker)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DJANGO_DB_NAME', default='glimpse_portal'),
        'USER': config('DJANGO_DB_USER', default='postgres'),
        'PASSWORD': config('DJANGO_DB_PASSWORD', default='postgres'),
        'HOST': config('DJANGO_DB_HOST', default='db'),
        'PORT': config('DJANGO_DB_PORT', default='5432'),
    }
}

# Supabase database - Business models
if SUPABASE_DATABASE_URL:
    DATABASES['supabase'] = dj_database_url.parse(
        SUPABASE_DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
else:
    DATABASES['supabase'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('SUPABASE_DB_NAME', default='postgres'),
        'USER': config('SUPABASE_DB_USER', default='postgres'),
        'PASSWORD': config('SUPABASE_DB_PASSWORD', default=''),
        'HOST': config('SUPABASE_DB_HOST', default='localhost'),
        'PORT': config('SUPABASE_DB_PORT', default='5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }

# Database Router - routes models to correct database
DATABASE_ROUTERS = ['config.routers.DatabaseRouter']


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = f'/{PORTAL_URL_PREFIX}/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

# Media files
MEDIA_URL = f'/{PORTAL_URL_PREFIX}/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login/Logout URLs
LOGIN_URL = f'/{PORTAL_URL_PREFIX}/login/'
LOGIN_REDIRECT_URL = f'/{PORTAL_URL_PREFIX}/'
LOGOUT_REDIRECT_URL = f'/{PORTAL_URL_PREFIX}/login/'

# CORS settings
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:8000,http://127.0.0.1:8000',
    cast=Csv()
)

# ===========================================
# REST API Security Settings
# ===========================================

# Django REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    # Rate limiting - reasonable limits for production
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',      # Anonymous users (shouldn't happen with token auth)
        'user': '1000/hour',     # Authenticated users (WordPress)
    },
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',
}

# API IP Whitelist (WordPress server IPs)
# Set to '*' for development, specific IPs for production
# Example: ALLOWED_API_IPS=1.2.3.4,5.6.7.8
ALLOWED_API_IPS = config('ALLOWED_API_IPS', default='', cast=Csv())

# ===========================================
# Caching Configuration
# ===========================================
# Using local memory cache for development
# Use Redis/Memcached in production for better performance
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'glimpse-api-cache',
        'TIMEOUT': 300,  # 5 minutes default
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
        }
    }
}

# For production with Redis (uncomment and configure):
# REDIS_URL = config('REDIS_URL', default=None)
# if REDIS_URL:
#     CACHES = {
#         'default': {
#             'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#             'LOCATION': REDIS_URL,
#         }
#     }

# Security settings for production
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='https://glimpseapp.net', cast=Csv())

# Debug toolbar settings
INTERNAL_IPS = ['127.0.0.1']

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'api': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'api_security': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'api_middleware': {
            'handlers': ['console'],
            'level': 'INFO',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
