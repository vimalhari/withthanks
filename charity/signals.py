"""
Django signal receivers for the charity app.

Registered via CharityConfig.ready() in apps.py.
"""

import logging
import os
import shutil

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_delete, sender="charity.Charity")
def cleanup_charity_media(sender, instance, **kwargs):
    """
    Delete individual media files attached to a Charity row when it is deleted.
    Also removes the per-charity media folder if it exists.
    """
    # No file fields remain on Charity after video defaults were moved to Campaign.

    charity_dir = os.path.join(settings.MEDIA_ROOT, "charities", f"charity_{instance.id}")
    if os.path.isdir(charity_dir):
        try:
            shutil.rmtree(charity_dir)
            logger.info("cleanup_charity_media: removed %s", charity_dir)
        except Exception as exc:
            logger.warning("cleanup_charity_media: could not remove %s: %s", charity_dir, exc)
