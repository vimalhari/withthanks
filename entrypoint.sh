#!/bin/bash
set -e
trap 'echo "ERROR: entrypoint.sh failed at line $LINENO (exit code $?)" >&2' ERR

is_true() {
  case "${1:-}" in
    [Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;;
    *) return 1 ;;
  esac
}

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

echo "Ensuring superuser exists..."
python manage.py ensure_superuser \
  --username "${DJANGO_SUPERUSER_USERNAME:-admin}" \
  --email "${DJANGO_SUPERUSER_EMAIL:-admin@withthanks.example.com}" \
  --password "${DJANGO_SUPERUSER_PASSWORD:-admin123!}"

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn withthanks.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers ${GUNICORN_WORKERS:-4} \
  --timeout ${GUNICORN_TIMEOUT:-120} \
  --access-logfile - \
  --error-logfile -
