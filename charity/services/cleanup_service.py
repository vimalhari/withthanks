"""
File-system cleanup logic.

Prunes old TTS cache files and generated video output files.
All public functions are pure Python so they can be tested or called from
management commands without a running Celery worker.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


def prune_voiceover_cache(*, older_than_days: int = 30) -> dict[str, int]:
    """
    Delete voiceover cache files older than *older_than_days* days.

    Called by the ``prune_voiceover_cache`` Celery beat task.

    Returns a dict with the count of files pruned.
    """
    from django.conf import settings

    cache_dir = os.path.join(settings.MEDIA_ROOT, "voiceover_cache")
    if not os.path.isdir(cache_dir):
        return {"pruned": 0}

    cutoff = time.time() - (older_than_days * 86400)
    pruned = 0
    for fname in os.listdir(cache_dir):
        fpath = os.path.join(cache_dir, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                pruned += 1
        except Exception as exc:
            logger.warning("Failed to prune %s: %s", fpath, exc)

    logger.info("Pruned %d old voiceover cache files", pruned)
    return {"pruned": pruned}


def remove_old_videos(*, older_than_days: int = 7) -> dict[str, int]:
    """
    Delete generated video files from ``VIDEO_OUTPUT_DIR`` older than
    *older_than_days* days.

    Called by the ``cleanup_old_videos`` Celery beat task.

    Returns a dict with the count of files deleted.
    """
    from django.conf import settings

    video_dir = str(settings.VIDEO_OUTPUT_DIR)
    if not os.path.isdir(video_dir):
        return {"deleted": 0}

    cutoff = time.time() - (older_than_days * 86400)
    deleted = 0
    for fname in os.listdir(video_dir):
        fpath = os.path.join(video_dir, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except Exception as exc:
            logger.warning("Failed to delete %s: %s", fpath, exc)

    logger.info("Deleted %d old video files from output dir", deleted)
    return {"deleted": deleted}
