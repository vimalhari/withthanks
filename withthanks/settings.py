import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# ------------------------------------------------------------
# Base directories and environment
# ------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ------------------------------------------------------------
# Core settings
# ------------------------------------------------------------
_secret_key = os.environ.get("DJANGO_SECRET_KEY")
_local_commands = {
    "runserver",
    "test",
    "shell",
    "check",
    "migrate",
    "makemigrations",
    "createsuperuser",
    "collectstatic",
    "seed_services",
    "tailwind",
}
_is_local_command = any(cmd in sys.argv for cmd in _local_commands)
_debug_env = os.environ.get("DJANGO_DEBUG")
DEBUG = _debug_env.lower() == "true" if _debug_env is not None else _is_local_command

if not _secret_key:
    if _is_local_command:
        _secret_key = "django-insecure-local-dev-secret-key-change-me"
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY environment variable must be set. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )
SECRET_KEY = _secret_key

# Accept a comma-separated list of extra hosts from the environment.
_extra_hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS = [
    # Only allow local hosts in development; production hosts must come from ALLOWED_HOSTS env var.
    *(["localhost", "127.0.0.1"] if DEBUG else []),
    *_extra_hosts,
]

# ------------------------------------------------------------
# Installed apps
# ------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_yasg",
    "django_tailwind_cli",
    "storages",
    "django_celery_beat",
    # Local
    "charity",
]

# ------------------------------------------------------------
# Middleware
# ------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files directly — must come right after SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ------------------------------------------------------------
# URL configuration
# ------------------------------------------------------------
ROOT_URLCONF = "withthanks.urls"

# Authentication redirects for login-required views.
LOGIN_URL = "charity_login"
LOGIN_REDIRECT_URL = "/charity/dashboard/"
LOGOUT_REDIRECT_URL = "/"

# ------------------------------------------------------------
# Templates
# ------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "charity.context_processors.charity_context",
            ]
        },
    }
]

# ------------------------------------------------------------
# WSGI / ASGI
# ------------------------------------------------------------
WSGI_APPLICATION = "withthanks.wsgi.application"
ASGI_APPLICATION = "withthanks.asgi.application"

# ------------------------------------------------------------
# Database
# Uses DATABASE_URL env-var when present (production / Coolify).
# Falls back to SQLite for local development.
# Format: postgresql://user:password@host:5432/dbname
# ------------------------------------------------------------
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    _parsed = urlparse(_db_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _parsed.path.lstrip("/"),
            "USER": _parsed.username or "",
            "PASSWORD": _parsed.password or "",
            "HOST": _parsed.hostname or "localhost",
            "PORT": str(_parsed.port or 5432),
            "OPTIONS": {"connect_timeout": 10},
            # Reuse DB connections for up to 10 minutes (avoids per-request reconnect overhead)
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "600")),
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ------------------------------------------------------------
# Django REST Framework
# ------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Session auth kept for the DRF browsable API in DEBUG mode.
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

# Add browsable API renderer only in debug mode so Swagger stays clean in prod.
if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(  # type: ignore[index]
        "rest_framework.renderers.BrowsableAPIRenderer"
    )

# ------------------------------------------------------------
# JWT settings (django-rest-framework-simplejwt)
# ------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=int(os.environ.get("JWT_ACCESS_HOURS", "1"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "7"))),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ------------------------------------------------------------
# Swagger / drf-yasg
# ------------------------------------------------------------
SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
        }
    },
    "USE_SESSION_AUTH": False,
}

# ------------------------------------------------------------
# Static and media
# ------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "assets" / "dist"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# ------------------------------------------------------------
# Tailwind CSS (django-tailwind-cli)
# ------------------------------------------------------------
TAILWIND_CLI_AUTOMATIC_DOWNLOAD = True
TAILWIND_CLI_SRC_CSS = "assets/src/styles.css"
TAILWIND_CLI_DIST_CSS = "css/tailwind.css"

MEDIA_URL = "/media/"
# In Docker the MEDIA_ROOT env-var is set to /app/media (volume mount).
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(BASE_DIR / "media")))

# ------------------------------------------------------------
# Video processing paths
# ------------------------------------------------------------
# Base video used when no campaign VideoTemplate is configured.
BASE_VIDEO_PATH = MEDIA_ROOT / "base_videos" / "newbase3.mp4"

# Output directory for generated / stitched videos.
VIDEO_OUTPUT_DIR = MEDIA_ROOT / "videos"
try:
    VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
except Exception as _e:
    print(f"⚠️ Could not create VIDEO_OUTPUT_DIR: {_e}")

# ------------------------------------------------------------
# Cloudflare Stream
# ------------------------------------------------------------
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_STREAM_TOKEN = os.environ.get("CLOUDFLARE_STREAM_TOKEN", "")
CLOUDFLARE_STREAM_ENABLED = os.environ.get("CLOUDFLARE_STREAM_ENABLED", "true").lower() == "true"

# ------------------------------------------------------------
# Cloudflare R2 — default object storage (S3-compatible)
# R2 is now the recommended default.  Set CLOUDFLARE_R2_BUCKET_NAME
# in your .env to enable.  Falls back to local FileSystemStorage
# when the bucket name is empty (e.g. quick local development).
# ------------------------------------------------------------
CLOUDFLARE_R2_ACCESS_KEY_ID = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
CLOUDFLARE_R2_BUCKET_NAME = os.environ.get("CLOUDFLARE_R2_BUCKET_NAME", "")
CLOUDFLARE_R2_ACCOUNT_ID = os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID", "")

_USE_R2 = bool(CLOUDFLARE_R2_BUCKET_NAME)
if _USE_R2:
    # S3-compatible endpoint for Cloudflare R2
    AWS_ACCESS_KEY_ID = CLOUDFLARE_R2_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY = CLOUDFLARE_R2_SECRET_ACCESS_KEY
    AWS_STORAGE_BUCKET_NAME = CLOUDFLARE_R2_BUCKET_NAME
    AWS_S3_ENDPOINT_URL = f"https://{CLOUDFLARE_R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    AWS_S3_REGION_NAME = "auto"
    # R2 does not support ACLs
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False

# Django 4.2+ STORAGES dict (replaces deprecated DEFAULT_FILE_STORAGE / STATICFILES_STORAGE).
STORAGES = {
    "default": {
        "BACKEND": (
            "storages.backends.s3boto3.S3Boto3Storage"
            if _USE_R2
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        # CompressedManifestStaticFilesStorage adds cache-busting hashes and gzip/brotli encoding.
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ------------------------------------------------------------
# Third-party API keys
# ------------------------------------------------------------
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_DEFAULT_VOICE_ID = os.environ.get("ELEVENLABS_DEFAULT_VOICE_ID", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

# ------------------------------------------------------------
# Email defaults
# ------------------------------------------------------------
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "No Reply <no-reply@example.com>")

# ------------------------------------------------------------
# Celery
# ------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes max per video task

# Celery Beat: use django-celery-beat database scheduler
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ------------------------------------------------------------
# Stripe
# ------------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY)

# ------------------------------------------------------------
# Timezone / internationalization
# ------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------
# Default primary key field type
# ------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "charity": {"handlers": ["console"], "level": "DEBUG"},
    },
}

# ------------------------------------------------------------
# CSRF Trusted Origins
# ------------------------------------------------------------
_csrf_origins = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    *_csrf_origins,
]

# ------------------------------------------------------------
# HTTPS / security hardening (production only)
# ------------------------------------------------------------
if not DEBUG:
    # Redirect all HTTP to HTTPS.
    SECURE_SSL_REDIRECT = True
    # Trust the X-Forwarded-Proto header set by Coolify / Nginx / Traefik.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # HSTS: tell browsers to only use HTTPS for 1 year, including subdomains.
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Only send session/CSRF cookies over HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Prevent browsers from MIME-sniffing the content type.
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ------------------------------------------------------------
# Upload size limits (stage3 needs large CSV/video uploads)
# ------------------------------------------------------------
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100 MB

# ------------------------------------------------------------
# Server base URL (used for tracking links in emails)
# ------------------------------------------------------------
SERVER_BASE_URL = os.environ.get("SERVER_BASE_URL", "http://127.0.0.1:8000")

# ------------------------------------------------------------
# ElevenLabs voice settings
# ------------------------------------------------------------
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", ELEVENLABS_DEFAULT_VOICE_ID)

# ------------------------------------------------------------
# Ensure media folders exist
# ------------------------------------------------------------
try:
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / "videos").mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / "voiceovers").mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / "base_videos").mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / "temp").mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / "outputs").mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / "voiceover_cache").mkdir(parents=True, exist_ok=True)
except Exception as _e:
    print(f"⚠️ Could not ensure media folders exist: {_e}")
