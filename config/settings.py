"""
Django settings for config project.
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-($jw#z4gtb@5euxes=iwjo1zl2%1jg-r(y_g%qaq%!7n))svxl",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")


# Application definition

INSTALLED_APPS = [
    # 'daphne' must be listed first — this is what makes `manage.py runserver`
    # ASGI-aware and able to handle WebSocket upgrade requests. Without it,
    # runserver falls back to plain WSGI and silently can't do WebSockets
    # at all (connections fail with close code 1006, not a clear error).
    'daphne',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # third-party
    'rest_framework',
    'corsheaders',
    'channels',

    # local
    'accounts',
    'chat',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# Database
# Defaults to SQLite for zero-setup local dev. Set DATABASE_* env vars to
# point at PostgreSQL (matches the original project plan) once you're ready.
if os.environ.get("DATABASE_NAME"):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get("DATABASE_NAME"),
            'USER': os.environ.get("DATABASE_USER", "postgres"),
            'PASSWORD': os.environ.get("DATABASE_PASSWORD", ""),
            'HOST': os.environ.get("DATABASE_HOST", "localhost"),
            'PORT': os.environ.get("DATABASE_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Custom user model (see accounts/models.py)
AUTH_USER_MODEL = 'accounts.User'


# Channels — channel layer used for group broadcast (rooms) across consumers.
# Redis-backed even in dev since that's the realistic target for Phase 5 scaling
# and it behaves the same locally as it will in production.
#
# socket_timeout/socket_connect_timeout are set generously (well above the
# channel layer's internal 5s BZPOPMIN block) with retry_on_timeout enabled,
# since Docker Desktop's networking layer (especially on Windows, via WSL2)
# can add latency that trips a too-tight default timeout and drops otherwise
# healthy connections.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                {
                    "host": os.environ.get("REDIS_HOST", "127.0.0.1"),
                    "port": int(os.environ.get("REDIS_PORT", 6379)),
                    "socket_timeout": 30,
                    "socket_connect_timeout": 30,
                    "retry_on_timeout": True,
                }
            ],
        },
    },
}


# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    # Global safety net — generous enough not to bother normal usage, but
    # stops a runaway client (buggy frontend code, a script, whatever)
    # from hammering the API unbounded. Auth endpoints get their own much
    # stricter rates below, since brute-forcing a login is the case that
    # actually matters most.
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
        'login': '5/min',
        'register': '3/min',
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
}


# CORS — Next.js dev server
CORS_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS", "http://localhost:3000"
).split(",")


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
