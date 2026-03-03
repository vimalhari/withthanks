"""
Batch and job management logic.

Houses operations that were previously embedded directly inside Celery tasks.
"""

from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)


def reset_stale_jobs(*, stale_after_hours: int = 2) -> dict[str, int]:
    """
    Reset ``DonationJob`` rows that have been stuck in ``"processing"``
    for longer than *stale_after_hours* hours back to ``"failed"``.

    Called by the ``cleanup_stale_jobs`` Celery beat task.

    Returns a dict with the count of jobs reset.
    """
    from django.utils.timezone import now

    from charity.models import DonationJob

    cutoff = now() - timedelta(hours=stale_after_hours)
    updated = DonationJob.objects.filter(
        status="processing",
        updated_at__lt=cutoff,
    ).update(
        status="failed",
        error_message=f"Stale job — timed out after {stale_after_hours} hours",
    )

    logger.info("Reset %d stale processing jobs to failed", updated)
    return {"stale_cleaned": updated}
