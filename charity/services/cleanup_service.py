"""
Cloud storage cleanup logic.

Prunes old voiceover cache files and generated video output files from R2
using Django's ``default_storage`` backend.  Nothing is read from or written
to the local filesystem.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_R2_VOICEOVER_CACHE_PREFIX = "voiceover_cache"
_R2_VIDEOS_PREFIX = "videos"


def prune_voiceover_cache(*, older_than_days: int = 30) -> dict[str, int]:
    """
    Delete voiceover cache files from R2 that are older than *older_than_days* days.

    Called by the ``prune_voiceover_cache`` Celery beat task.
    Returns a dict with the count of files pruned.
    """
    from django.core.files.storage import default_storage

    pruned = _delete_old_storage_files(
        storage=default_storage,
        prefix=_R2_VOICEOVER_CACHE_PREFIX,
        older_than_days=older_than_days,
    )
    logger.info("Pruned %d old voiceover cache files from R2", pruned)
    return {"pruned": pruned}


def remove_old_videos(*, older_than_days: int = 7) -> dict[str, int]:
    """
    Delete generated video files from R2 that are older than *older_than_days* days.

    Called by the ``cleanup_old_videos`` Celery beat task.
    Returns a dict with the count of files deleted.
    """
    from django.core.files.storage import default_storage

    deleted = _delete_old_storage_files(
        storage=default_storage,
        prefix=_R2_VIDEOS_PREFIX,
        older_than_days=older_than_days,
    )
    logger.info("Deleted %d old video files from R2", deleted)
    return {"deleted": deleted}


def _delete_old_storage_files(*, storage, prefix: str, older_than_days: int) -> int:
    """
    List all files under *prefix* in *storage* and delete those whose
    last-modified time is older than *older_than_days* days.

    Returns the number of files deleted.
    """
    import datetime

    from django.utils import timezone

    cutoff = timezone.now() - datetime.timedelta(days=older_than_days)
    deleted = 0

    try:
        _dirs, files = storage.listdir(prefix)
    except Exception as exc:
        logger.warning("Could not list storage prefix '%s': %s", prefix, exc)
        return 0

    for fname in files:
        key = f"{prefix}/{fname}"
        try:
            modified_time = storage.get_modified_time(key)
            if modified_time is not None and modified_time < cutoff:
                storage.delete(key)
                deleted += 1
        except Exception as exc:
            logger.warning("Failed to prune '%s': %s", key, exc)

    return deleted
