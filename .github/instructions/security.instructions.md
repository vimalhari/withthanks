---
description: Security, multi-tenancy, and deployment best practices
applyTo: "**"
---

# Security & Deployment Instructions

## Multi-Tenancy Security (CRITICAL)
- This is a multi-tenant SaaS app. Data leaks between charities are security incidents.
- EVERY database query involving user data MUST be scoped to the active charity.
- Use `get_active_charity(request)` from `charity.utils.access_control` for FBVs.
- Use `ActiveCharityMixin` for CBVs.
- Never use `Model.objects.all()` in user-facing views without charity filtering.
- Always verify charity membership when accepting `charity_id` in API requests.

## Authentication & Authorization
- Web UI: Django session authentication with `@login_required`.
- REST API: JWT via `Bearer` token (`djangorestframework-simplejwt`).
- Permission hierarchy: `IsAuthenticated` → `IsCharityMember` → `IsCharityAdmin`.
- Superusers bypass all charity-level permission checks.
- New views MUST have either `@login_required` or DRF permission classes.

## Secrets Management
- All secrets loaded from `.env` via `python-dotenv`.
- NEVER hardcode API keys, tokens, or passwords in source code.
- NEVER commit `.env` files. The `.gitignore` must exclude them.
- Use `os.environ.get("KEY", "default")` pattern from settings.py.

## Input Validation
- API: Validate all input at the DRF serializer level.
- Web forms: Use Django ModelForm validation.
- CSV uploads: Validate headers, data types, and row counts before processing.
- File uploads: Validate MIME types and file sizes.
- Sanitize all user input rendered in templates to prevent XSS.

## CSRF Protection
- All HTML forms must include `{% csrf_token %}`.
- AJAX requests must include the CSRF token from the cookie.
- API endpoints using JWT are exempt from CSRF (stateless auth).

## Production Security Headers
- `SECURE_SSL_REDIRECT = True` (HTTPS enforced in production).
- HSTS enabled with 1-year max-age, subdomains, and preload.
- Session and CSRF cookies marked `Secure` in production.
- `SECURE_CONTENT_TYPE_NOSNIFF = True`.
- X-Forwarded-Proto trusted for reverse proxy (Coolify/Nginx/Traefik).

## Deployment (Coolify)
- Docker-based deployment via `docker-compose.yml`.
- Entry point: `entrypoint.sh`.
- Health check endpoint: `GET /health/` → `{"status": "ok"}`.
- Static files served by WhiteNoise (no separate Nginx for statics).
- Media files stored in Cloudflare R2 (production) or local filesystem (dev).
- Redis as Celery broker and result backend.
- PostgreSQL as production database.

