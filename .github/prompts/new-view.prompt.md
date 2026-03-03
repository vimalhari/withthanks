---
description: "Generate a new Django view following WithThanks FBV patterns"
---

# New Django View

Create a function-based view following WithThanks conventions.

## Requirements
- Use `@login_required` decorator for all authenticated views.
- Call `get_active_charity(request)` to resolve the current tenant.
- Handle the case where no active charity is found (redirect with error message).
- Keep the view thin — delegate any business logic to services in `charity/services/`.
- Use Django `messages` framework for user-facing feedback.
- Scope ALL querysets to the active charity.

## Template
```python
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .utils.access_control import get_active_charity

logger = logging.getLogger(__name__)


@login_required
def ${1:view_name}(request):
    """${2:Description of what this view does}."""
    charity = get_active_charity(request)
    if not charity:
        messages.error(request, "No active charity context.")
        return redirect("dashboard")

    # Query data scoped to the active charity
    # queryset = Model.objects.filter(charity=charity)

    context = {
        "charity": charity,
    }
    return render(request, "${3:template_name.html}", context)
```

## After Creating
1. Add the view to the appropriate `views_*.py` module.
2. Import it in `charity/views.py` if needed for re-export.
3. Add URL pattern in `charity/urls.py`.
4. Create the template file.
