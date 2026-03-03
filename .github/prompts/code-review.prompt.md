---
description: "Review code changes for WithThanks quality standards and security"
---

# Code Review

Review code changes against WithThanks project standards.

## Checklist

### Multi-Tenancy (CRITICAL)
- [ ] Every queryset is scoped to `charity=get_active_charity(request)` or equivalent.
- [ ] No use of `.objects.all()` in user-facing views without charity filtering.
- [ ] API endpoints validate charity membership for any `charity_id` parameter.
- [ ] Tests verify cross-tenant data isolation.

### Security
- [ ] No hardcoded secrets, API keys, or passwords.
- [ ] All forms include `{% csrf_token %}`.
- [ ] New views have `@login_required` or appropriate DRF permission classes.
- [ ] User input is validated (serializer or form level).
- [ ] File uploads validate MIME type and size.

### Code Quality
- [ ] `from __future__ import annotations` at top of new modules.
- [ ] Logging uses `logger = logging.getLogger(__name__)`.
- [ ] Business logic is in `charity/services/`, not in views or tasks.
- [ ] Double quotes used consistently (Ruff enforced).
- [ ] Line length ≤ 100 characters.
- [ ] Imports sorted: stdlib → third-party → first-party.

### Database
- [ ] New models have `charity` FK for multi-tenancy.
- [ ] `select_related` / `prefetch_related` used to avoid N+1 queries.
- [ ] `help_text` on non-obvious model fields.
- [ ] Migration generated after model changes.

### Celery Tasks
- [ ] `@shared_task(bind=True)` decorator used.
- [ ] Task added to `CELERY_TASK_ROUTES` with correct queue.
- [ ] Error handling with `FatalTaskError` for unrecoverable failures.
- [ ] Temporary files cleaned up in `finally` blocks.

### Templates
- [ ] Extends `base_dashboard.html` for authenticated pages.
- [ ] Tailwind CSS utilities only — no custom CSS.
- [ ] `{% url 'name' %}` for all links (no hardcoded URLs).
- [ ] Django messages framework used for user feedback.

## Running Quality Checks
```bash
make lint       # Ruff lint check
make format     # Ruff auto-format
make typecheck  # Pyright type checking
make test       # Run all tests
```
