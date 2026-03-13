---
description: "Generate a new service module following WithThanks service layer patterns"
---

# New Service Module

Create a service module in `charity/services/` following WithThanks conventions.

## Requirements
- Services contain business logic — keep views and tasks thin.
- Use composition over inheritance (plain functions or simple classes).
- Add `from __future__ import annotations` at the top.
- Use proper logging with `logger = logging.getLogger(__name__)`.
- Services should be testable in isolation (accept dependencies as parameters).
- Handle external API errors gracefully with retries where appropriate.

## Template
```python
"""
${1:Service name} — ${2:brief description}.

This module encapsulates ${3:what business domain this covers}.
Called by views/tasks; never imports from views/tasks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from charity.models import Charity

logger = logging.getLogger(__name__)


def ${4:function_name}(charity: Charity, ${5:params}) -> ${6:ReturnType}:
    """${7:What this function does}.

    Args:
        charity: The charity context (multi-tenancy scope).
        ${5}: Description of parameters.

    Returns:
        ${6}: Description of return value.

    Raises:
        ValueError: When input validation fails.
    """
    logger.info("${4} starting for charity=%s", charity.id)

    # Business logic here

    logger.info("${4} completed for charity=%s", charity.id)
    return result
```

## Existing Services
- `video_build_service.py` — FFmpeg video composition (`VideoSpec`, `build_personalized_video`)
- `video_pipeline_service.py` — Cloudflare Stream upload (`StreamDelivery`, `stream_safe_upload`)
- `invoice_service.py` — invoice generation and lifecycle management
- `batch_service.py` — batch processing coordination
- `cleanup_service.py` — file and data cleanup operations
- `analytics_service.py` — analytics data aggregation

## After Creating
1. Import and use from the appropriate task or view.
2. Add tests that mock external API calls.
