---
description: "Generate a new Django model with WithThanks conventions"
---

# New Django Model

Create a Django model following WithThanks conventions.

## Requirements
- Add `from __future__ import annotations` at the top of the module.
- Use `models.BigAutoField` (inherited from `DEFAULT_AUTO_FIELD` setting).
- Include `charity = models.ForeignKey("Charity", on_delete=models.CASCADE)` for multi-tenancy.
- Add `created_at = models.DateTimeField(auto_now_add=True)`.
- Add `help_text` on every non-obvious field.
- Use `uuid.uuid4` for public-facing identifiers.
- Include a `__str__` method.
- Include a `class Meta` with `ordering` and `verbose_name_plural`.

## Template
```python
from __future__ import annotations

import uuid
from django.db import models


class ${1:ModelName}(models.Model):
    """${2:Description of the model}."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(
        "Charity",
        on_delete=models.CASCADE,
        related_name="${3:related_name}",
        help_text="The charity this ${1} belongs to.",
    )
    # Add fields here
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "${4:plural_name}"

    def __str__(self) -> str:
        return f"${1} ({self.id})"
```

## After Creating
1. Register the model in `charity/admin.py`.
2. Run `uv run python manage.py makemigrations`.
3. Run `uv run python manage.py migrate`.
