# WithThanks — GitHub Copilot Instructions

## Project Overview

**WithThanks** is a multi-tenant SaaS platform that generates personalised donor thank-you videos for charities/nonprofits. It processes CSV uploads of donations, generates TTS voiceovers (ElevenLabs), composites personalised videos (FFmpeg), uploads to Cloudflare Stream, and emails donors with tracked links.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Framework | Django 6.0 |
| API | Django REST Framework (DRF) + SimpleJWT |
| Task Queue | Celery 5.x + Redis broker |
| Scheduler | django-celery-beat (DB scheduler) |
| Database | PostgreSQL (prod) / SQLite (dev) |
| Object Storage | Cloudflare R2 via django-storages (S3-compat) |
| Video CDN | Cloudflare Stream |
| TTS | ElevenLabs API |
| Email | Resend API |
| Billing | Stripe |
| CSS | Tailwind CSS (django-tailwind-cli) |
| Static Files | WhiteNoise |
| Package Manager | uv |
| Linting | Ruff |
| Type Checking | Pyright + django-stubs |
| API Docs | drf-yasg (Swagger/ReDoc) |
| Containerization | Docker + docker-compose |
| Deployment | Coolify |

## Architecture

```
withthanks/          ← Django project config (settings, urls, celery, wsgi)
charity/             ← Main (and only) Django app
  api/               ← DRF API views + serializers (JSON ingest endpoints)
  services/          ← Business logic services (video build, pipeline, invoicing)
  utils/             ← Utility modules (media, resend, cloudflare, exports, access control)
  templates/         ← Django HTML templates (Tailwind CSS)
  templatetags/      ← Custom template tags
  management/        ← Django management commands
  migrations/        ← Database migrations
  static/            ← App-level static assets
assets/src/          ← Tailwind CSS source (styles.css)
media/               ← User uploads and generated files
```

## Key Conventions

### Python / Django
- **Python 3.12+** — use modern syntax: `match`, `type` aliases, `X | Y` unions, f-strings.
- **Line length**: 100 characters (Ruff enforced).
- **Quotes**: Double quotes (`"`).
- **Imports**: Sorted with `isort` via Ruff. First-party packages: `charity`, `withthanks`.
- **Models**: Use `BigAutoField` as default PK. Always specify `help_text` on non-obvious fields.
- **Views**: Function-based views (FBVs) are predominant. CBVs use `LoginRequiredMixin` + `ActiveCharityMixin`.
- **Multi-tenancy**: Every queryset MUST be scoped to the active charity via `get_active_charity(request)`. Never leak data across tenants.
- **Forms**: Use Django ModelForm with explicit `fields` list. Add Tailwind CSS classes via `widgets`.
- **Migrations**: Always run `makemigrations` after model changes. Never manually edit migration files.
- Always prefer `from __future__ import annotations` in new modules.

### REST API (DRF)
- Authentication: JWT via `Bearer` token header.
- All API views require `IsAuthenticated` or custom `IsCharityMember` / `IsCharityAdmin` permissions.
- Serializers: Use `serializers.Serializer` for ingest, `ModelSerializer` for CRUD.
- Validate at the serializer level, not in views.

### Celery Tasks
- Decorate with `@shared_task(bind=True)`.
- Three queues: `video` (heavy), `default` (orchestration), `maintenance` (periodic).
- Route tasks via `CELERY_TASK_ROUTES` in settings.
- Use `chord`/`chain`/`group` for multi-step workflows.
- Always handle `FatalTaskError` and log failures.

### Templates
- Base layout: `base_dashboard.html` (authenticated) / `layouts/` directory.
- Use Tailwind CSS utility classes — no custom CSS unless absolutely necessary.
- Template tags live in `charity/templatetags/charity_extras.py`.

### Code Quality
- **Lint**: `make lint` (Ruff check)
- **Format**: `make format` (Ruff format)
- **Type check**: `make typecheck` (Pyright)
- **Test**: `make test` (Django test runner)

### Running the Project
- `make dev` — start dev server (`uv run python manage.py runserver`)
- `make worker` — start Celery worker
- `make beat` — start Celery beat scheduler
- `make migrate` — run migrations

### Environment Variables
All secrets and configuration are loaded from `.env` via `python-dotenv`. Never hardcode secrets. Key env vars:
- `DJANGO_SECRET_KEY`, `DATABASE_URL`, `CELERY_BROKER_URL`
- `ELEVENLABS_API_KEY`, `RESEND_API_KEY`
- `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_STREAM_TOKEN`
- `CLOUDFLARE_R2_*` (access key, secret, bucket, account)
- `SERVER_BASE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`

## Response Guidelines
- When generating Django code, always follow the existing patterns in this project.
- Prefer composition over inheritance for services.
- Keep views thin — delegate business logic to `charity/services/`.
- When writing tests, follow the pattern in `charity/tests.py` — use `TestCase`, `Client`, mock external APIs.
- Always consider multi-tenant isolation when writing queries.
- Use `select_related` / `prefetch_related` for queryset optimization.
- Return proper HTTP status codes from API endpoints.
