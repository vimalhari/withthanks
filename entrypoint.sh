#!/bin/bash

echo "📦 Waiting for database to be ready..."
# optional: wait for DB if you’re using PostgreSQL/MySQL
sleep 5

echo "🧩 Applying database migrations..."
python manage.py migrate --noinput

echo "👤 Collecting static files..."
python manage.py collectstatic --noinput

echo "🚀 Starting Django server..."
exec python manage.py runserver 0.0.0.0:8000
