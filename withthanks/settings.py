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
DEBUG = False

ALLOWED_HOSTS = [
    "hirefella.com",
    "www.hirefella.com",
    "localhost",
    "127.0.0.1",
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
STATIC_ROOT = BASE_DIR / "staticfiles"

# 🧩 Inside Docker container
MEDIA_URL = "/media/"
MEDIA_ROOT = Path("/app/media")  # volume-mounted from Jenkins host path

# ------------------------------------------------------------
# Video processing paths
# ------------------------------------------------------------
# ✅ Base video path inside container
BASE_VIDEO_PATH = MEDIA_ROOT / "base_videos" / "newbase3.mp4"

# ✅ Directory for generated or stitched videos
VIDEO_OUTPUT_DIR = MEDIA_ROOT / "videos"
VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# Email defaults
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
# Logging for debugging video and ffmpeg operations
# ------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "charity": {"handlers": ["console"], "level": "DEBUG"},
    },
}

# ------------------------------------------------------------
# CSRF Trusted Origins
# ------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = [
    "https://hirefella.com",
    "https://www.hirefella.com",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# ------------------------------------------------------------
# Optional: ensure upload folder exists for video generation
# ------------------------------------------------------------
try:
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    (MEDIA_ROOT / "videos").mkdir(parents=True, exist_ok=True)
except Exception as e:
    print(f"⚠️ Could not ensure media folders exist: {e}")
