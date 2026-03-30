"""
Django settings for Glimpse Portal.

This portal runs at glimpseapp.net/portal and serves as the admin interface.
"""

from pathlib import Path
from decouple import config, Csv
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.templatetags.static import static

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
    'unfold',
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
    'portal.apps.PortalConfig',
]

UNFOLD = {
    "SITE_TITLE": "Glimpse Portal",
    "SITE_HEADER": "Glimpse Portal",
    "SITE_SYMBOL": "hub",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "ENVIRONMENT": "portal.dashboard.environment_callback",
    "DASHBOARD_CALLBACK": "portal.dashboard.dashboard_callback",
    "COLORS": {
        "primary": {
            "50": "oklch(97.5% .01 250)",
            "100": "oklch(94% .02 250)",
            "200": "oklch(88% .04 250)",
            "300": "oklch(80% .08 250)",
            "400": "oklch(70% .14 250)",
            "500": "oklch(60% .19 250)",
            "600": "oklch(52% .2 250)",
            "700": "oklch(45% .18 250)",
            "800": "oklch(38% .15 250)",
            "900": "oklch(30% .12 250)",
            "950": "oklch(22% .09 250)",
        },
        "danger": {
            "50": "oklch(97% .01 20)",
            "100": "oklch(94% .03 20)",
            "200": "oklch(88% .06 20)",
            "300": "oklch(80% .10 20)",
            "400": "oklch(70% .14 20)",
            "500": "oklch(62% .16 20)",
            "600": "oklch(55% .15 20)",
            "700": "oklch(48% .13 20)",
            "800": "oklch(40% .11 20)",
            "900": "oklch(32% .08 20)",
            "950": "oklch(24% .06 20)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Dashboard"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Home"),
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                    {
                        "title": _("CF Analytics"),
                        "icon": "insights",
                        "link": reverse_lazy("admin:cf_analytics"),
                    },
                    {
                        "title": _("Live Feed"),
                        "icon": "stream",
                        "link": reverse_lazy("live_feed:dashboard"),
                    },
                ],
            },
            {
                "title": _("Content"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("News"),
                        "icon": "article",
                        "link": reverse_lazy("admin:data_news_changelist"),
                    },
                    {
                        "title": _("Videos"),
                        "icon": "smart_display",
                        "link": reverse_lazy("admin:data_videos_changelist"),
                    },
                    {
                        "title": _("Publishers"),
                        "icon": "group_work",
                        "link": reverse_lazy("admin:data_videopublishers_changelist"),
                    },
                    {
                        "title": _("Categories"),
                        "icon": "category",
                        "link": reverse_lazy("admin:data_categories_changelist"),
                    },
                ],
            },
            {
                "title": _("Taxonomy"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Divisions"),
                        "icon": "lan",
                        "link": reverse_lazy("admin:data_divisions_changelist"),
                    },
                    {
                        "title": _("Source Aliases"),
                        "icon": "link",
                        "link": reverse_lazy("admin:data_sourcealias_changelist"),
                    },
                    {
                        "title": _("Topics"),
                        "icon": "label",
                        "link": reverse_lazy("admin:data_topics_changelist"),
                    },
                    {
                        "title": _("Extra Details"),
                        "icon": "info",
                        "link": reverse_lazy("admin:data_extradetails_changelist"),
                    },
                    {
                        "title": _("Timelines"),
                        "icon": "timeline",
                        "link": reverse_lazy("admin:data_timelines_changelist"),
                    },
                ],
            },
            {
                "title": _("Access"),
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": _("Users"),
                        "icon": "person",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                    {
                        "title": _("Groups"),
                        "icon": "groups",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                    {
                        "title": _("API Tokens"),
                        "icon": "vpn_key",
                        "link": reverse_lazy("admin:authtoken_tokenproxy_changelist"),
                    },
                ],
            },
        ],
    },
}

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
# Database Configuration
# ===========================================
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

# CF Worker origin path secret — protects /origin/ from direct access
ORIGIN_PATH_SECRET = config('ORIGIN_PATH_SECRET', default='')

# Live feed control-plane settings (Django -> Worker publish)
WORKER_BASE_URL = config('WORKER_BASE_URL', default='https://glimpseapp.net')
APP_SECRET = config('APP_SECRET', default='')
LIVE_FEED_ADMIN_TOKEN = config('LIVE_FEED_ADMIN_TOKEN', default='')

# ===========================================
# Caching Configuration (Redis)
# ===========================================
REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'TIMEOUT': 300,  # 5 minutes default
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Fallback to local memory cache if Redis is not available (development)
if not REDIS_URL or REDIS_URL == 'none':
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'glimpse-api-cache',
            'TIMEOUT': 300,
            'OPTIONS': {
                'MAX_ENTRIES': 1000,
            }
        }
    }

# Security settings for production
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='https://glimpseapp.net', cast=Csv())

# YouTube API
YOUTUBE_API_KEY = config('YOUTUBE_API_KEY', default='')

# Cloudflare Analytics Engine (for admin CF analytics dashboard)
# CF_ANALYTICS_TOKEN must be a Cloudflare API token with "Account Analytics: Read" permission.
# Create one at: https://dash.cloudflare.com/profile/api-tokens
CF_ACCOUNT_ID = config('CF_ACCOUNT_ID', default='')
CF_ANALYTICS_TOKEN = config('CF_ANALYTICS_TOKEN', default='')

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
