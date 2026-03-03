---
description: Django models, views, forms, and ORM conventions for the WithThanks charity app
applyTo: "charity/**/*.py,withthanks/**/*.py"
---

# Django Development Instructions

## Module Header
Always start new Python modules with:
```python
from __future__ import annotations
```

## Models (`charity/models.py`)
- Use `models.BigAutoField` (project default via `DEFAULT_AUTO_FIELD`).
- Add `help_text` on every field that isn't self-documenting.
- Always include `created_at = models.DateTimeField(auto_now_add=True)` on new models.
- Use `uuid.uuid4` for public-facing identifiers; integer PKs for internal FK references.
- Foreign keys to `Charity` model must always use `on_delete=models.CASCADE`.
- New models must include `charity = models.ForeignKey("Charity", on_delete=models.CASCADE)` for multi-tenancy unless there's an explicit reason not to.

## Multi-Tenancy (CRITICAL)
- Every queryset in views/services MUST be scoped via `get_active_charity(request)` from `charity.utils.access_control`.
- Pattern for FBVs:
  ```python
  @login_required
  def my_view(request):
      charity = get_active_charity(request)
      if not charity:
          messages.error(request, "No active charity.")
          return redirect("dashboard")
      qs = MyModel.objects.filter(charity=charity)
  ```
- Pattern for CBVs: use `ActiveCharityMixin` from `charity/mixins.py`:
  ```python
  class MyView(LoginRequiredMixin, ActiveCharityMixin, View):
      def get(self, request):
          qs = MyModel.objects.filter(charity=self.charity)
  ```
- NEVER use `.objects.all()` in views without charity scoping.

## Views
- Prefer function-based views (FBVs) with `@login_required` decorator.
- Keep views thin — no business logic; delegate to `charity/services/`.
- View modules are split by domain:
  - `views.py` — dashboard, imports/re-exports
  - `views_auth.py` — login, register, password
  - `views_batch.py` — CSV upload, batch reports
  - `views_billing.py` — Stripe billing
  - `views_campaign.py` — campaign CRUD
  - `views_clients.py` — client management
  - `views_invoices.py` — invoice CRUD
  - `views_invoice_actions.py` — mark-paid, void, send
  - `views_invoice_exports.py` — PDF, CSV, JSON export
  - `views_revenue.py` — revenue intelligence
  - `views_tracking.py` — open/click tracking pixels
  - `views_webhooks.py` — Stripe webhooks
  - `views_admin.py` — superuser admin views
  - `views_analytics.py` — analytics dashboard

## Forms (`charity/forms.py`)
- Always use `ModelForm` with explicit `fields` list.
- Add Tailwind CSS classes via `widgets` dict, e.g.:
  ```python
  widgets = {
      "name": forms.TextInput(attrs={"class": "saas-input", "placeholder": "Name"}),
  }
  ```

## QuerySet Optimization
- Use `select_related()` for ForeignKey / OneToOne traversals.
- Use `prefetch_related()` for ManyToMany / reverse FK sets.
- Use `.only()` / `.defer()` when loading large models for list views.
- Use `Count`, `Sum`, `Avg` aggregations instead of Python-side loops.

## Migrations
- After any model change run: `uv run python manage.py makemigrations`
- Never hand-edit migration files.
- Use `RunPython` with both forward and reverse functions for data migrations.

## Error Handling
- Use Django `messages` framework for user-facing errors in views.
- Use `charity.exceptions.FatalTaskError` in Celery tasks for unrecoverable failures.
- Use proper logging: `logger = logging.getLogger(__name__)` at module level.

## Imports
- Follow Ruff isort ordering: stdlib → third-party → first-party (`charity`, `withthanks`).
- Use relative imports within the `charity` app (e.g., `from .models import Charity`).
- Use absolute imports for cross-app references (e.g., `from withthanks.settings import ...` — but prefer `django.conf.settings`).
