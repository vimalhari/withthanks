---
description: "Set up a new feature end-to-end: model, service, view, template, URL, and tests"
---

# New Feature (End-to-End)

Scaffold a complete feature across all layers of the WithThanks stack.

## Steps

### 1. Model (`charity/models.py`)
- Add the model with `charity` FK for multi-tenancy.
- Include `created_at`, `help_text`, and `__str__`.
- Run `uv run python manage.py makemigrations && uv run python manage.py migrate`.

### 2. Service (`charity/services/<feature>_service.py`)
- Create a service module with business logic.
- Accept `charity` parameter for tenant scoping.
- Keep it testable with dependency injection for external services.

### 3. Form (if web UI) (`charity/forms.py`)
- Add a `ModelForm` with explicit `fields` list.
- Add Tailwind classes via `widgets`.

### 4. Serializer (if API) (`charity/api/serializers.py`)
- Use `Serializer` for ingest, `ModelSerializer` for CRUD.
- Validate at serializer level.

### 5. View
- **FBV** in `charity/views_<feature>.py`:
  - `@login_required`
  - `get_active_charity(request)` for tenant scoping
  - Delegate to service
- **API** in `charity/api/views.py`:
  - Permission class: `IsCharityMember` or `IsCharityAdmin`
  - Return proper status codes

### 6. URL Route
- Web: Add to `charity/urls.py`
- API: Add to `charity/api/urls.py`

### 7. Template (`charity/templates/<feature>.html`)
- Extend `base_dashboard.html`
- Tailwind CSS utilities only

### 8. Celery Task (if async processing needed)
- Add to `charity/tasks.py`
- Route in `CELERY_TASK_ROUTES`

### 9. Tests
- Add to `charity/tests.py` or `charity/tests_<feature>.py`
- Test multi-tenant isolation
- Mock external APIs

### 10. Admin (optional)
- Register model in `charity/admin.py`

## Verification
```bash
make lint       # Code style
make format     # Auto-format
make typecheck  # Type checking
make test       # All tests pass
make dev        # Manual verification
```
