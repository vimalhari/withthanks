# withthanks/settings.py — minimal dev settings (safe to run locally)
import os
from pathlib import Path
from dotenv import load_dotenv

# ------------------------------------------------------------
# Base directories and environment
# ------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ------------------------------------------------------------
# Core settings
# ------------------------------------------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-do-not-use-in-prod")
DEBUG = True

ALLOWED_HOSTS = ["hirefella.com", "www.hirefella.com"]

# -----------------------------------------------------------
# Installed apps
# ------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "charity",  # your app
]

# ------------------------------------------------------------
# Middleware
# ------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# ------------------------------------------------------------
# URL configuration
# ------------------------------------------------------------
ROOT_URLCONF = "withthanks.urls"

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
# ------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ------------------------------------------------------------
# Static and media
# ------------------------------------------------------------
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ------------------------------------------------------------
# Email defaults (for resend utils or local fallback)
# ------------------------------------------------------------
DEFAULT_FROM_EMAIL = "No Reply <no-reply@tanjavoorathefe.in>"

# ------------------------------------------------------------
# Timezone / internationalization
# ------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# ------------------------------------------------------------
# Video processing paths
# ------------------------------------------------------------
# ✅ Correct base video file path
BASE_VIDEO_PATH = BASE_DIR / "media" / "base_videos" / "newbase3.mp4"

# Directory for temporary or stitched output videos
VIDEO_OUTPUT_DIR = BASE_DIR / "tmp_videos"
VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# Optional: logging for ffmpeg and CSV processing
# ------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

CSRF_TRUSTED_ORIGINS = [
    "https://hirefella.com",
    "https://www.hirefella.com"
]