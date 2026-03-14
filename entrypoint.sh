#!/bin/bash
set -e
trap 'echo "ERROR: entrypoint.sh failed at line $LINENO (exit code $?)" >&2' ERR

is_true() {
  case "${1:-}" in
    [Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;;
    *) return 1 ;;
  esac
}

require_env() {
  local var_name="$1"
  if [ -z "${!var_name:-}" ]; then
    echo "$var_name must be set in production." >&2
    exit 1
  fi
}

if [ "${DJANGO_ENV:-development}" = "production" ]; then
  require_env DJANGO_SECRET_KEY
  require_env DJANGO_SUPERUSER_PASSWORD
  require_env ALLOWED_HOSTS
  require_env CSRF_TRUSTED_ORIGINS
  require_env DEFAULT_FROM_EMAIL
  require_env SERVER_BASE_URL
fi

echo "Applying database migrations..."
python manage.py migrate --noinput

if is_true "${SEED_DATA_ON_START:-false}"; then
  SEED_MARKER="${SEED_DATA_MARKER_FILE:-/app/media/.seed_data_initialized}"
  if [ -f "$SEED_MARKER" ] && ! is_true "${SEED_DATA_FORCE:-false}"; then
    echo "Seed data already initialized ($SEED_MARKER). Skipping."
  else
    echo "Seeding demo data..."
    if is_true "${SEED_DATA_NO_INVOICES:-false}"; then
      python manage.py seed_data --no-invoices
    else
      python manage.py seed_data
    fi
    mkdir -p "$(dirname "$SEED_MARKER")"
    touch "$SEED_MARKER"
    echo "Seed data initialization complete."
  fi
fi

if is_true "${SEED_ANALYTICS_ON_START:-false}"; then
  echo "Seeding analytics events..."
  if is_true "${SEED_ANALYTICS_FORCE:-false}"; then
    python manage.py seed_analytics --force
  else
    python manage.py seed_analytics
  fi
fi

echo "Ensuring superuser exists..."
python manage.py ensure_superuser \
  --username "${DJANGO_SUPERUSER_USERNAME:-admin}" \
  --email "${DJANGO_SUPERUSER_EMAIL:-admin@withthanks.example.com}" \
  --password "${DJANGO_SUPERUSER_PASSWORD:-}"

echo "Starting Gunicorn..."
exec gunicorn withthanks.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers ${GUNICORN_WORKERS:-4} \
  --timeout ${GUNICORN_TIMEOUT:-120} \
  --access-logfile - \
  --error-logfile -
