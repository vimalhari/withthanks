"""
Shared video delivery utilities used by the staged ``DonationJob`` pipeline.

Cloudflare Stream uploads, public fallback URL resolution, and tracking URL
construction live here so the Celery tasks stay focused on orchestration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.conf import settings
from django.urls import reverse

if TYPE_CHECKING:
    from charity.models import Campaign
    from charity.utils.cloudflare_stream import StreamUploadResult

logger = logging.getLogger(__name__)


def _as_absolute_url(url_or_path: str, server_url: str) -> str:
    """Return an absolute URL for a storage-backed asset or hosted URL."""
    if not url_or_path:
        return ""
    if url_or_path.startswith(("http://", "https://")):
        return url_or_path
    return f"{server_url.rstrip('/')}/{url_or_path.lstrip('/')}"


def resolve_storage_video_url(*, storage_path: str | None, server_url: str) -> str:
    """Resolve a storage key or relative media URL to a public absolute URL."""
    if not storage_path:
        return ""

    if storage_path.startswith(("http://", "https://")):
        return storage_path

    from django.core.files.storage import default_storage

    try:
        storage_url = default_storage.url(storage_path)
    except Exception as exc:
        logger.warning("Failed to resolve storage URL for %r: %s", storage_path, exc)
        return ""

    return _as_absolute_url(storage_url, server_url)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StreamDelivery:
    """Holds resolved Cloudflare Stream identifiers for a single video send."""

    video_id: str = field(default="")
    playback_url: str = field(default="")
    thumbnail_url: str = field(default="")

    @property
    def is_uploaded(self) -> bool:
        return bool(self.video_id)


@dataclass
class TrackingUrls:
    """Resolved pixel / click / unsubscribe URLs for an outbound email."""

    pixel_url: str
    click_url: str
    unsubscribe_url: str | None


# ---------------------------------------------------------------------------
# Cloudflare Stream helpers
# ---------------------------------------------------------------------------


def stream_safe_upload(video_path: str, *, meta_name: str = "") -> StreamUploadResult | None:
    """
    Upload *video_path* to Cloudflare Stream and return the result.

    Returns ``None`` (instead of raising) when:
    - ``CLOUDFLARE_STREAM_ENABLED`` is ``False`` / unset
    - The upload fails for any reason

    This keeps both pipelines non-fatal on Stream errors while still
    falling back to attachment / local-URL delivery.
    """
    from charity.utils.cloudflare_stream import upload_video_to_stream

    if not getattr(settings, "CLOUDFLARE_STREAM_ENABLED", False):
        return None

    try:
        result = upload_video_to_stream(video_path, meta_name=meta_name)
        logger.info(
            "CF Stream upload OK  video_id=%s  url=%s",
            result.video_id,
            result.playback_url,
        )
        return result
    except Exception as exc:
        logger.warning(
            "CF Stream upload failed for %r — falling back to local delivery. Error: %s",
            video_path,
            exc,
        )
        return None


def get_or_upload_campaign_stream(campaign: Campaign, video_path: str) -> StreamDelivery:
    """
    Return the Cloudflare Stream URL for *campaign*, uploading once if needed.

    Used by the VDM flow in the CSV pipeline where all donors in the same
    campaign share an identical base video.  The result is cached on the
    ``Campaign`` model so subsequent jobs skip the upload entirely.

    Returns a :class:`StreamDelivery` (may be empty when CF is disabled or
    the upload fails).
    """
    if not getattr(settings, "CLOUDFLARE_STREAM_ENABLED", False):
        return StreamDelivery()

    if campaign.cf_stream_video_url:
        logger.debug(
            "Reusing cached CF Stream URL for campaign %s: %s",
            campaign.id,
            campaign.cf_stream_video_url,
        )
        return StreamDelivery(
            video_id=campaign.cf_stream_video_id or "",
            playback_url=campaign.cf_stream_video_url,
        )

    # First job for this campaign — upload and cache.
    result = stream_safe_upload(
        video_path,
        meta_name=f"{campaign.name} — VDM",
    )
    if result:
        campaign.cf_stream_video_id = result.video_id
        campaign.cf_stream_video_url = result.playback_url
        campaign.save(update_fields=["cf_stream_video_id", "cf_stream_video_url"])
        return StreamDelivery(
            video_id=result.video_id,
            playback_url=result.playback_url,
            thumbnail_url=result.thumbnail_url,
        )

    return StreamDelivery()


# ---------------------------------------------------------------------------
# Tracking URL helpers
# ---------------------------------------------------------------------------


def build_tracking_urls(
    *,
    job_id: int,
    mode: str,
    server_url: str,
    tracking_token: str | None = None,
    campaign_id: int | None = None,
    batch_id: int | None = None,
    suppress_unsubscribe: bool = False,
) -> TrackingUrls:
    """
    Build pixel / click / unsubscribe URLs for a single outbound donor email.

    Args:
        job_id: The ``DonationJob.id`` used as the primary tracking key.
        mode: The campaign mode string (e.g. ``"VDM"``, ``"WithThanks"``).
        server_url: Base URL without trailing slash (e.g. ``"https://example.com"``).
        campaign_id: Optional campaign PK appended as ``&c=<id>``.
        batch_id: Optional batch PK appended as ``&b=<id>``.
        suppress_unsubscribe: Pass ``True`` for THANKYOU campaigns to omit
            the unsubscribe link entirely.
    """
    if tracking_token:
        qs_suffix = f"t={tracking_token}"
    else:
        qs_suffix = f"u={job_id}&type={mode}"
        if campaign_id:
            qs_suffix += f"&c={campaign_id}"
        if batch_id:
            qs_suffix += f"&b={batch_id}"

    pixel_url = f"{server_url}{reverse('track_open')}?{qs_suffix}"
    click_url = f"{server_url}{reverse('track_click')}?{qs_suffix}"

    unsubscribe_url: str | None = None
    if not suppress_unsubscribe:
        unsubscribe_url = f"{server_url}{reverse('track_unsubscribe_full')}?{qs_suffix}"

    return TrackingUrls(
        pixel_url=pixel_url,
        click_url=click_url,
        unsubscribe_url=unsubscribe_url,
    )


# ---------------------------------------------------------------------------
# Public video URL resolver
# ---------------------------------------------------------------------------


def resolve_public_video_url(
    *,
    final_video_path: str | None,
    stream_delivery: StreamDelivery,
    server_url: str,
    storage_video_path: str | None = None,
) -> str:
    """
    Return the public-facing URL to embed in the outbound email.

    Prefers the Cloudflare Stream CDN URL when available. When Stream is
    unavailable, falls back to a persisted/public storage URL and never leaks
    a worker-local temp path such as ``/tmp/...`` into donor emails.
    """
    if stream_delivery.is_uploaded:
        return stream_delivery.playback_url

    if final_video_path and final_video_path.startswith(("http://", "https://")):
        return final_video_path

    if final_video_path and final_video_path.startswith("/media/"):
        return _as_absolute_url(final_video_path, server_url)

    return resolve_storage_video_url(storage_path=storage_video_path, server_url=server_url)
