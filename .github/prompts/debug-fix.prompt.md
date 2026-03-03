---
description: "Fix a bug in the WithThanks codebase with systematic debugging approach"
---

# Debug & Fix

Systematically debug and fix an issue in the WithThanks codebase.

## Debugging Workflow

1. **Reproduce** — Identify the exact steps or input that trigger the bug.
2. **Locate** — Search for the relevant code using the error traceback or symptoms.
3. **Understand** — Read surrounding code context to understand the intended behavior.
4. **Fix** — Apply the minimal change that resolves the issue.
5. **Verify** — Run `make test` to ensure no regressions.
6. **Lint** — Run `make lint` and `make format` to ensure code quality.

## Common Issue Areas

### Multi-Tenancy Leaks
- Check that all querysets are filtered by `charity=get_active_charity(request)`.
- Verify that API endpoints validate `charity_id` against user memberships.
- Run `charity/tests_multi_tenancy.py` to verify isolation.

### Celery Task Failures
- Check `charity/tasks.py` for proper error handling and state management.
- Verify task routing in `CELERY_TASK_ROUTES` settings.
- Check that `select_related` includes all needed joins.
- Look for file cleanup issues in intermediate processing steps.

### Template Rendering Errors
- Verify template context variables are passed from the view.
- Check for missing `{% load %}` tags.
- Ensure `{% url %}` names match `urls.py` patterns.

### API Issues
- Check serializer validation logic.
- Verify JWT token is valid and not expired.
- Confirm permission classes are correctly applied.
- Check `request.data` vs `request.query_params` usage.

## After Fixing
1. Run `make test` — verify all tests pass.
2. Run `make lint` — verify code style.
3. Run `make format` — auto-format if needed.
4. Run `make typecheck` — verify type annotations.
