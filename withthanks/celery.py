"""
Celery application for WithThanks.

Autodiscovers tasks from all installed Django apps and configures
the Beat scheduler for periodic tasks.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "withthanks.settings")

app = Celery("withthanks")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodiscover tasks in all INSTALLED_APPS (looks for tasks.py in each app).
app.autodiscover_tasks()

# ---------------------------------------------------------------------------
# Periodic tasks (Celery Beat)
# These run on the beat scheduler (django-celery-beat DatabaseScheduler).
# They can also be managed via Django Admin → Periodic Tasks.
# ---------------------------------------------------------------------------
app.conf.beat_schedule = {
    # Refresh materialized CampaignStats every 15 minutes
    "refresh-campaign-stats": {
        "task": "charity.tasks.refresh_all_campaign_stats",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "maintenance"},
    },
    # Mark overdue invoices (daily at 6 AM UTC)
    "mark-overdue-invoices": {
        "task": "charity.tasks.mark_overdue_invoices",
        "schedule": crontab(hour=6, minute=0),
        "options": {"queue": "maintenance"},
    },
    # Clean up stale processing jobs older than 2 hours (every 30 min)
    "cleanup-stale-jobs": {
        "task": "charity.tasks.cleanup_stale_jobs",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "maintenance"},
    },
    # Prune voiceover cache files older than 30 days (daily at 3 AM UTC)
    "prune-voiceover-cache": {
        "task": "charity.tasks.prune_voiceover_cache",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "maintenance"},
    },
    # Clean up generated video files older than 7 days (daily at 4 AM UTC)
    "cleanup-old-videos": {
        "task": "charity.tasks.cleanup_old_videos",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "maintenance"},
    },
}
