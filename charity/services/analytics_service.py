"""
Analytics business logic extracted from Celery tasks.

All public functions are pure Python — no Celery imports.  Tasks simply
call them and forward the return value.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def rebuild_all_campaign_stats() -> dict[str, int]:
    """
    Refresh the materialized ``CampaignStats`` row for every campaign.

    Returns a dict with the count of refreshed campaigns.
    """
    from charity.models import Campaign
    from charity.models_analytics import CampaignStats

    campaigns = Campaign.objects.all()
    refreshed = 0
    for campaign in campaigns:
        stats, _ = CampaignStats.objects.get_or_create(campaign=campaign)
        stats.update_stats()
        refreshed += 1

    logger.info("Refreshed CampaignStats for %d campaigns", refreshed)
    return {"refreshed": refreshed}
