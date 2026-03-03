.PHONY: dev test lint format typecheck migrate shell export-reqs worker beat

# ── Development ─────────────────────────────────────────────────────────────
dev:
	uv run python manage.py runserver

migrate:
	uv run python manage.py migrate

shell:
	uv run python manage.py shell

worker:
	uv run celery -A withthanks worker --loglevel=info --concurrency=2 --queues=video,default

beat:
	uv run celery -A withthanks beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

# ── Code quality ─────────────────────────────────────────────────────────────
lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run pyright

# ── Testing ───────────────────────────────────────────────────────────────────
test:
	uv run python manage.py test charity

test-verbose:
	uv run python manage.py test charity --verbosity=2

# ── Requirements export (keep requirements.txt in sync for non-uv platforms) ─
export-reqs:
	uv export --no-hashes --no-dev -o requirements.txt
