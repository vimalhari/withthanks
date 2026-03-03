"""
charity.services — public API surface.

Import from the sub-modules for direct access.  This file registers the
available services so that ``from charity.services import <name>`` works
for the most commonly used entry-points.
"""

# Analytics
from .analytics_service import rebuild_all_campaign_stats

# Batch / job management
from .batch_service import reset_stale_jobs

# File-system cleanup
from .cleanup_service import prune_voiceover_cache, remove_old_videos

# Invoice operations
from .invoice_service import calculate_invoice_totals, generate_invoice_number, mark_overdue_bulk

# Shared video delivery layer
from .video_pipeline_service import (
    StreamDelivery,
    TrackingUrls,
    build_tracking_urls,
    get_or_upload_campaign_stream,
    resolve_public_video_url,
    stream_safe_upload,
)

__all__ = [  # noqa: RUF022
    # analytics
    "rebuild_all_campaign_stats",
    # batch
    "reset_stale_jobs",
    # cleanup
    "prune_voiceover_cache",
    "remove_old_videos",
    # invoice
    "calculate_invoice_totals",
    "generate_invoice_number",
    "mark_overdue_bulk",
    # video pipeline
    "StreamDelivery",
    "TrackingUrls",
    "build_tracking_urls",
    "get_or_upload_campaign_stream",
    "resolve_public_video_url",
    "stream_safe_upload",
]
