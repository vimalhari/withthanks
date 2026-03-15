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

from charity.utils.cloudflare_stream import extract_stream_video_id

if TYPE_CHECKING:
    from charity.models import Campaign
    from charity.utils.cloudflare_stream import StreamUploadResult

logger = logging.getLogger(__name__)


def _storage_uses_local_filesystem() -> bool:
    """Return True when Django is serving uploads from local disk."""
    from django.core.files.storage import default_storage

    return default_storage.__class__.__module__ == "django.core.files.storage.filesystem"


def _as_absolute_url(url_or_path: str, server_url: str) -> str:
    """Return an absolute URL for a storage-backed asset or hosted URL."""
    if not url_or_path:
        return ""
    if url_or_path.startswith(("http://", "https://")):
        return url_or_path
    return f"{server_url.rstrip('/')}/{url_or_path.lstrip('/')}"


def _is_private_r2_api_url(url: str) -> bool:
    """Return True when the URL points at the Cloudflare R2 S3 API endpoint."""
    return ".r2.cloudflarestorage.com" in url


def resolve_storage_video_url(*, storage_path: str | None, server_url: str) -> str:
    """Resolve a storage key to a public absolute URL when the backend is externally reachable."""
    if not storage_path:
        return ""

    if storage_path.startswith(("http://", "https://")):
        return storage_path

    from django.core.files.storage import default_storage

    try:
        if not default_storage.exists(storage_path):
            logger.warning("Storage path %r does not exist; treating as non-public.", storage_path)
            return ""
    except Exception as exc:
        logger.warning("Failed to verify storage path %r existence: %s", storage_path, exc)
        return ""

    try:
        storage_url = default_storage.url(storage_path)
    except Exception as exc:
        logger.warning("Failed to resolve storage URL for %r: %s", storage_path, exc)
        return ""

    if _storage_uses_local_filesystem():
        logger.warning(
            "Resolved storage path %r to local filesystem URL %r; treating as non-public.",
            storage_path,
            storage_url,
        )
        return ""

    if _is_private_r2_api_url(storage_url):
        public_media_base_url = getattr(settings, "PUBLIC_MEDIA_BASE_URL", "")
        if not public_media_base_url:
            logger.warning(
                "Resolved storage path %r to private R2 API URL %r without PUBLIC_MEDIA_BASE_URL; treating as non-public.",
                storage_path,
                storage_url,
            )
            return ""

        return f"{public_media_base_url}/{storage_path.lstrip('/')}"

    return _as_absolute_url(storage_url, server_url)


def resolve_static_asset_url(*, static_path: str | None, server_url: str) -> str:
    """Resolve a compiled static asset path to a public absolute URL."""
    if not static_path:
        return ""

    from django.contrib.staticfiles.storage import staticfiles_storage

    try:
        static_url = staticfiles_storage.url(static_path)
    except Exception as exc:
        logger.warning("Failed to resolve static asset URL for %r: %s", static_path, exc)
        return ""

    return _as_absolute_url(static_url, server_url)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StreamDelivery:
    """Holds resolved Cloudflare Stream identifiers for a single video send."""

    video_id: str = field(default="")
    playback_url: str = field(default="")
    thumbnail_url: str = field(default="")
    is_cached: bool = field(default=False)

    @property
    def is_uploaded(self) -> bool:
        return bool(self.playback_url)


def _build_stream_thumbnail_url(video_id: str) -> str:
    """Build the default Cloudflare Stream thumbnail URL for a known video id."""
    if not video_id:
        return ""
    return f"https://videodelivery.net/{video_id}/thumbnails/thumbnail.jpg?time=2s&height=320"


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

    This keeps upload errors non-fatal at the helper level; the caller can
    decide whether a failed upload should abort donor delivery.
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
        video_id = campaign.cf_stream_video_id or extract_stream_video_id(
            campaign.cf_stream_video_url
        )

        if video_id and campaign.cf_stream_video_id != video_id:
            campaign.cf_stream_video_id = video_id
            campaign.save(update_fields=["cf_stream_video_id"])

        logger.debug(
            "Reusing cached CF Stream URL for campaign %s: %s",
            campaign.id,
            campaign.cf_stream_video_url,
        )
        return StreamDelivery(
            video_id=video_id,
            playback_url=campaign.cf_stream_video_url,
            thumbnail_url=_build_stream_thumbnail_url(video_id),
            is_cached=True,
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
            thumbnail_url=result.thumbnail_url or _build_stream_thumbnail_url(result.video_id),
            is_cached=False,
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
    unavailable, only returns an externally reachable storage URL and never
    leaks a worker-local or local-media filesystem path into donor emails.
    """
    if stream_delivery.is_uploaded:
        return stream_delivery.playback_url

    if final_video_path and final_video_path.startswith(("http://", "https://")):
        return final_video_path

    return resolve_storage_video_url(storage_path=storage_video_path, server_url=server_url)
