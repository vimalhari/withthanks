#!/bin/bash
set -e
trap 'echo "ERROR: entrypoint.sh failed at line $LINENO (exit code $?)" >&2' ERR

echo "Applying database migrations..."
python manage.py migrate --noinput

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
