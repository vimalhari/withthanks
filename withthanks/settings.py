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
DJANGO_ENV = os.environ.get("DJANGO_ENV", "development").strip().lower()
IS_PRODUCTION = DJANGO_ENV == "production"

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
    "seed_data",
    "seed_analytics",
    "tailwind",
}
_build_only_commands = {"collectstatic", "tailwind"}
_is_build_only_command = any(cmd in sys.argv for cmd in _build_only_commands)
_is_local_command = any(cmd in sys.argv for cmd in _local_commands)
_debug_env = os.environ.get("DJANGO_DEBUG")
DEBUG = (
    _debug_env.lower() == "true"
    if _debug_env is not None
    else _is_local_command and not IS_PRODUCTION
)

if not _secret_key:
    if _is_build_only_command or (_is_local_command and not IS_PRODUCTION):
        _secret_key = "django-insecure-local-dev-secret-key-change-me"
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY environment variable must be set. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(50))"'
        )
SECRET_KEY = _secret_key

if IS_PRODUCTION and DEBUG and not _is_build_only_command:
    raise RuntimeError("DJANGO_DEBUG must be false in production.")

# Accept a comma-separated list of extra hosts from the environment.
_extra_hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS = [
    # Only allow local hosts in development; production hosts must come from ALLOWED_HOSTS env var.
    *(["localhost", "127.0.0.1"] if DEBUG else []),
    *_extra_hosts,
]

if IS_PRODUCTION and not _extra_hosts and not _is_build_only_command:
    raise RuntimeError("ALLOWED_HOSTS must be set in production.")

# ------------------------------------------------------------
# Installed apps
# ------------------------------------------------------------
INSTALLED_APPS = [
    # Unfold admin theme — must come before django.contrib.admin
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
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
# Django Unfold Admin
# ------------------------------------------------------------
UNFOLD = {
    "SITE_TITLE": "WithThanks",
    "SITE_HEADER": "WithThanks Admin",
    "SITE_URL": "/charity/",
    "SITE_ICON": None,
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Client Management",
                "items": [
                    {
                        "title": "Charities (Clients)",
                        "icon": "business",
                        "link": "/admin/charity/charity/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": "Members",
                        "icon": "group",
                        "link": "/admin/charity/charitymember/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
            {
                "title": "Campaigns & Donations",
                "items": [
                    {
                        "title": "Campaigns",
                        "icon": "campaign",
                        "link": "/admin/charity/campaign/",
                    },
                    {
                        "title": "Donation Batches",
                        "icon": "folder",
                        "link": "/admin/charity/donationbatch/",
                    },
                    {
                        "title": "Donation Jobs",
                        "icon": "work",
                        "link": "/admin/charity/donationjob/",
                    },
                    {
                        "title": "Donors",
                        "icon": "person",
                        "link": "/admin/charity/donor/",
                    },
                    {
                        "title": "Donations",
                        "icon": "attach_money",
                        "link": "/admin/charity/donation/",
                    },
                ],
            },
            {
                "title": "Billing & Invoicing",
                "items": [
                    {
                        "title": "Invoices",
                        "icon": "receipt",
                        "link": "/admin/charity/invoice/",
                    },
                    {
                        "title": "Services",
                        "icon": "sell",
                        "link": "/admin/charity/invoiceservice/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": "Line Items",
                        "icon": "format_list_bulleted",
                        "link": "/admin/charity/invoicelineitem/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
            {
                "title": "Analytics & Logs",
                "items": [
                    {
                        "title": "Video Send Log",
                        "icon": "send",
                        "link": "/admin/charity/videosendlog/",
                    },
                    {
                        "title": "Unsubscribed Users",
                        "icon": "unsubscribe",
                        "link": "/admin/charity/unsubscribeduser/",
                    },
                    {
                        "title": "Received Emails",
                        "icon": "mark_email_read",
                        "link": "/admin/charity/receivedemail/",
                    },
                    {
                        "title": "Campaign Stats",
                        "icon": "bar_chart",
                        "link": "/admin/charity/campaignstats/",
                    },
                    {
                        "title": "Email Events",
                        "icon": "email",
                        "link": "/admin/charity/emailevent/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": "Video Events",
                        "icon": "play_circle",
                        "link": "/admin/charity/videoevent/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": "Watch Sessions",
                        "icon": "timer",
                        "link": "/admin/charity/watchsession/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
            {
                "title": "Celery Beat",
                "items": [
                    {
                        "title": "Periodic Tasks",
                        "icon": "schedule",
                        "link": "/admin/django_celery_beat/periodictask/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                ],
            },
        ],
    },
}

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
# WSGI
# ------------------------------------------------------------
WSGI_APPLICATION = "withthanks.wsgi.application"

# ------------------------------------------------------------
# Password Validation
# ------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

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
# Base video fallback path (used only for local dev without R2).
BASE_VIDEO_PATH = MEDIA_ROOT / "base_videos" / "newbase3.mp4"

# ------------------------------------------------------------
# Cloudflare Stream
# ------------------------------------------------------------
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_STREAM_TOKEN = os.environ.get("CLOUDFLARE_STREAM_TOKEN", "")
CLOUDFLARE_STREAM_ENABLED = os.environ.get("CLOUDFLARE_STREAM_ENABLED", "true").lower() == "true"

# ------------------------------------------------------------
# Cloudflare R2 — default object storage (S3-compatible)
# R2 is now the recommended default. Set the full credential set in your
# .env to enable it. Falls back to local FileSystemStorage when the R2
# configuration is absent (e.g. quick local development).
# ------------------------------------------------------------
CLOUDFLARE_R2_ACCESS_KEY_ID = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
CLOUDFLARE_R2_BUCKET_NAME = os.environ.get("CLOUDFLARE_R2_BUCKET_NAME", "")
CLOUDFLARE_R2_ACCOUNT_ID = os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID", "")

_r2_settings = {
    "CLOUDFLARE_R2_ACCESS_KEY_ID": CLOUDFLARE_R2_ACCESS_KEY_ID,
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": CLOUDFLARE_R2_SECRET_ACCESS_KEY,
    "CLOUDFLARE_R2_BUCKET_NAME": CLOUDFLARE_R2_BUCKET_NAME,
    "CLOUDFLARE_R2_ACCOUNT_ID": CLOUDFLARE_R2_ACCOUNT_ID,
}
_has_any_r2_setting = any(_r2_settings.values())
_missing_r2_settings = [name for name, value in _r2_settings.items() if not value]

if IS_PRODUCTION and _has_any_r2_setting and _missing_r2_settings and not _is_build_only_command:
    missing_names = ", ".join(_missing_r2_settings)
    raise RuntimeError(f"Incomplete Cloudflare R2 configuration in production: {missing_names}")

_USE_R2 = not _missing_r2_settings
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

PUBLIC_MEDIA_BASE_URL = os.environ.get("PUBLIC_MEDIA_BASE_URL", "").rstrip("/")

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
# Resend webhook signing secret (starts with "whsec_" from your Resend dashboard)
RESEND_WEBHOOK_SECRET = os.environ.get("RESEND_WEBHOOK_SECRET", "")
# Cloudflare webhook secret
CLOUDFLARE_WEBHOOK_SECRET = os.environ.get("CLOUDFLARE_WEBHOOK_SECRET", "")

# ------------------------------------------------------------
# Blackbaud SKY API (shared application credentials)
# Per-charity tokens are stored on the Charity model.
# ------------------------------------------------------------
BLACKBAUD_CLIENT_ID = os.environ.get("BLACKBAUD_CLIENT_ID", "")
BLACKBAUD_CLIENT_SECRET = os.environ.get("BLACKBAUD_CLIENT_SECRET", "")
# Blackbaud Ocp-Apim-Subscription-Key — required header on every SKY API request
BLACKBAUD_SUBSCRIPTION_KEY = os.environ.get("BLACKBAUD_SUBSCRIPTION_KEY", "")
# Must match the redirect URI registered in your Blackbaud developer portal
BLACKBAUD_REDIRECT_URI = os.environ.get(
    "BLACKBAUD_REDIRECT_URI",
    f"{os.environ.get('SERVER_BASE_URL', 'http://localhost:8000').rstrip('/')}/charity/crm/blackbaud/callback/",
)

# ------------------------------------------------------------
# Email defaults
# ------------------------------------------------------------
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "No Reply <no-reply@example.com>")

if (
    IS_PRODUCTION
    and DEFAULT_FROM_EMAIL == "No Reply <no-reply@example.com>"
    and not _is_build_only_command
):
    raise RuntimeError("DEFAULT_FROM_EMAIL must be set in production.")

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
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 min hard kill (SIGKILL)
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # 25 min soft limit — allows graceful cleanup
CELERY_RESULT_EXPIRES = 60 * 60 * 24  # Keep results in Redis for 24 h then auto-expire

# Celery Beat: use django-celery-beat database scheduler
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ---------------------------------------------------------------------------
# Queue routing
# ---------------------------------------------------------------------------
# Three queues:
#   video       - CPU/I-O heavy tasks (TTS, FFmpeg, email send)
#   default     - lightweight orchestration (batch_process_csv, callbacks)
#   maintenance - periodic beat tasks so they're never blocked by video work

from kombu import Queue  # noqa: E402

CELERY_TASK_QUEUES = (
    Queue("video"),
    Queue("default"),
    Queue("maintenance"),
)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ROUTES = {
    # Orchestration / callbacks — default queue
    "charity.tasks.batch_process_csv": {"queue": "default"},
    "charity.tasks.on_batch_complete": {"queue": "default"},
    # Periodic maintenance — isolated from video work
    "charity.tasks.refresh_all_campaign_stats": {"queue": "maintenance"},
    "charity.tasks.mark_overdue_invoices": {"queue": "maintenance"},
    "charity.tasks.cleanup_stale_jobs": {"queue": "maintenance"},
    "charity.tasks.prune_voiceover_cache": {"queue": "maintenance"},
    "charity.tasks.cleanup_old_videos": {"queue": "maintenance"},
}

# Optional: e-mail address that receives batch-completion admin notifications.
# If unset, admin e-mail notifications are silently skipped.
ADMIN_NOTIFICATION_EMAIL = os.environ.get("ADMIN_NOTIFICATION_EMAIL", "")

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
    *(["http://127.0.0.1:8000", "http://localhost:8000"] if DEBUG else []),
    *_csrf_origins,
]

if IS_PRODUCTION and not _csrf_origins and not _is_build_only_command:
    raise RuntimeError("CSRF_TRUSTED_ORIGINS must be set in production.")

if IS_PRODUCTION and not _is_build_only_command:
    invalid_csrf_origins = [origin for origin in _csrf_origins if not origin.startswith("https://")]
    if invalid_csrf_origins:
        raise RuntimeError("CSRF_TRUSTED_ORIGINS must use https in production.")

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

if IS_PRODUCTION and not _is_build_only_command:
    if SERVER_BASE_URL == "http://127.0.0.1:8000":
        raise RuntimeError("SERVER_BASE_URL must be set in production.")
    parsed_server_base_url = urlparse(SERVER_BASE_URL)
    if parsed_server_base_url.scheme != "https" or not parsed_server_base_url.netloc:
        raise RuntimeError("SERVER_BASE_URL must be a valid https URL in production.")

# ------------------------------------------------------------
# ElevenLabs voice settings
# ------------------------------------------------------------
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", ELEVENLABS_DEFAULT_VOICE_ID)

# ------------------------------------------------------------
# Ensure base media root exists (R2 handles all sub-directories)
# ------------------------------------------------------------
try:
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
except Exception as _e:
    print(f"⚠️ Could not ensure MEDIA_ROOT exists: {_e}")

# ------------------------------------------------------------
# Sentry error monitoring (production)
# Set SENTRY_DSN in your .env.prod to enable.
# Sign up free at https://sentry.io or self-host.
# ------------------------------------------------------------
_sentry_dsn = os.environ.get("SENTRY_DSN", "")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        environment=os.environ.get("DJANGO_ENV", "development"),
        # Capture 10% of transactions for performance tracing.
        # Increase to 1.0 temporarily to debug performance issues.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        # Don't send PII (email addresses etc.) to Sentry by default.
        send_default_pii=False,
    )
