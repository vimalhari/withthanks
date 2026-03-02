"""
Cloudflare Stream integration.

After FFmpeg generates a personalised video on disk, call
``upload_video_to_stream`` to push it to Cloudflare Stream and receive a
hosted playback URL plus auto-generated thumbnail - both of which are stored
on ``VideoSendLog`` and embedded in the donor e-mail instead of attaching
the raw MP4.

Required environment variables
--------------------------------
CLOUDFLARE_ACCOUNT_ID   - your Cloudflare account identifier
CLOUDFLARE_STREAM_TOKEN - an API token with *Stream:Edit* permissions

Optional
--------
CLOUDFLARE_STREAM_ENABLED - set to "false" to bypass Stream entirely and
                             fall back to e-mail attachments (default: "true")
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CF_BASE = "https://api.cloudflare.com/client/v4/accounts"


@dataclass(frozen=True)
class StreamUploadResult:
    video_id: str
    playback_url: str
    thumbnail_url: str


def _credentials() -> tuple[str, str]:
    from django.conf import settings

    account_id = getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "") or os.environ.get(
        "CLOUDFLARE_ACCOUNT_ID", ""
    )
    api_token = getattr(settings, "CLOUDFLARE_STREAM_TOKEN", "") or os.environ.get(
        "CLOUDFLARE_STREAM_TOKEN", ""
    )
    if not account_id or not api_token:
        raise RuntimeError(
            "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_STREAM_TOKEN must be set in the environment."
        )
    return account_id, api_token


def upload_video_to_stream(
    file_path: str,
    *,
    meta_name: str = "",
) -> StreamUploadResult:
    """Upload a local MP4 to Cloudflare Stream.

    Args:
        file_path: Absolute path to the video file on disk.
        meta_name: Human-readable label stored in Cloudflare's dashboard.

    Returns:
        A :class:`StreamUploadResult` with ``video_id``, ``playback_url``,
        and ``thumbnail_url`` populated.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        RuntimeError: If credentials are missing.
        httpx.HTTPStatusError: If the Cloudflare API returns a non-2xx status.
    """
    account_id, api_token = _credentials()

    file = Path(file_path)
    if not file.exists():
        raise FileNotFoundError(f"Video file not found: {file}")

    url = f"{_CF_BASE}/{account_id}/stream"
    headers = {"Authorization": f"Bearer {api_token}"}

    with open(file, "rb") as fh:
        response = httpx.post(
            url,
            headers=headers,
            files={"file": (file.name, fh, "video/mp4")},
            data={"meta": f'{{"name": "{meta_name}"}}'},
            timeout=180.0,
        )

    response.raise_for_status()
    result = response.json().get("result", {})

    video_id: str = result.get("uid", "")

    # Cloudflare returns a hosted player URL in ``preview``.
    playback_url: str = result.get(
        "preview",
        f"https://watch.cloudflarestream.com/{video_id}",
    )

    # Cloudflare auto-generates a thumbnail; fall back to a predictable URL.
    thumbnail_url: str = result.get(
        "thumbnail",
        f"https://videodelivery.net/{video_id}/thumbnails/thumbnail.jpg?time=2s&height=320",
    )

    logger.info("✅ Cloudflare Stream upload: uid=%s  player=%s", video_id, playback_url)
    return StreamUploadResult(
        video_id=video_id,
        playback_url=playback_url,
        thumbnail_url=thumbnail_url,
    )
