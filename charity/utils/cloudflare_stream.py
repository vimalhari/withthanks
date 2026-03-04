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


# ---------------------------------------------------------------------------
# Cloudflare Stream GraphQL Analytics
# ---------------------------------------------------------------------------

_CF_GRAPHQL = "https://api.cloudflare.com/client/v4/graphql"

_STREAM_ANALYTICS_QUERY = """
query StreamAnalytics($accountTag: string!, $start: Date, $end: Date, $uids: [string!]) {
  viewer {
    accounts(filter: {accountTag: $accountTag}) {
      videoPlaybackEventsAdaptiveGroups(
        filter: { date_geq: $start, date_lt: $end, uid_in: $uids }
        orderBy: [sum_timeViewedMinutes_DESC]
        limit: 5000
      ) {
        count
        sum { timeViewedMinutes }
        dimensions { uid }
      }
    }
  }
}
"""


def get_stream_video_analytics(
    video_uids: list[str],
    date_from: str,
    date_to: str,
) -> dict[str, dict]:
    """Query Cloudflare Stream GraphQL for per-video play counts and minutes viewed.

    CF GraphQL max window is 31 days and retention is 90 days.  If the
    requested range exceeds 31 days this function automatically splits it into
    multiple requests and merges the results.

    Args:
        video_uids: List of Cloudflare Stream video UIDs to query.
        date_from: ISO date string ``YYYY-MM-DD`` (inclusive).
        date_to:   ISO date string ``YYYY-MM-DD`` (exclusive end).

    Returns:
        Dict keyed by video UID::

            {
                "<uid>": {
                    "plays": int,
                    "minutes_viewed": float,
                }
            }

    Returns an empty dict gracefully if credentials are missing or API errors occur.
    """
    from datetime import date, timedelta

    if not video_uids:
        return {}

    try:
        account_id, api_token = _credentials()
    except RuntimeError:
        logger.warning("CF Stream analytics: credentials not configured")
        return {}

    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError:
        return {}

    # Split into ≤31-day windows (CF API limit)
    results: dict[str, dict] = {}
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=31), end)
        _fetch_stream_window(
            account_id=account_id,
            api_token=api_token,
            video_uids=video_uids,
            start=window_start.isoformat(),
            end=window_end.isoformat(),
            results=results,
        )
        window_start = window_end

    return results


def _fetch_stream_window(
    account_id: str,
    api_token: str,
    video_uids: list[str],
    start: str,
    end: str,
    results: dict,
) -> None:
    """Fetch one ≤31-day window from the CF Stream GraphQL API, merging into results."""
    try:
        resp = httpx.post(
            _CF_GRAPHQL,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json={
                "query": _STREAM_ANALYTICS_QUERY,
                "variables": {
                    "accountTag": account_id,
                    "start": start,
                    "end": end,
                    "uids": video_uids,
                },
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        groups = (
            data.get("data", {})
            .get("viewer", {})
            .get("accounts", [{}])[0]
            .get("videoPlaybackEventsAdaptiveGroups", [])
        )
        for group in groups:
            uid = group.get("dimensions", {}).get("uid", "")
            if not uid:
                continue
            plays = group.get("count", 0) or 0
            minutes = (group.get("sum") or {}).get("timeViewedMinutes", 0.0) or 0.0
            if uid in results:
                results[uid]["plays"] += plays
                results[uid]["minutes_viewed"] += minutes
            else:
                results[uid] = {"plays": plays, "minutes_viewed": round(minutes, 2)}
    except Exception as exc:
        logger.warning("CF Stream GraphQL window %s-%s failed: %s", start, end, exc)


# ---------------------------------------------------------------------------
# Cloudflare R2 Storage — per-charity usage via S3-compatible ListObjectsV2
# ---------------------------------------------------------------------------


def get_r2_storage_by_prefix() -> dict[str, dict]:
    """List R2 bucket objects and aggregate size/count by top-level prefix.

    Uses the S3-compatible API with the R2 credentials from Django settings.
    Results are cached for 1 hour to avoid hammering the API.

    Returns a dict keyed by prefix (typically charity-id or folder name)::

        {
            "outputs": {"objects": 142, "bytes": 1234567890, "gb": 1.15, "cost_usd": 0.017},
            "voiceovers": {...},
            ...
        }

    Returns an empty dict if credentials are not configured.
    """
    from django.conf import settings
    from django.core.cache import cache

    cache_key = "r2_storage_summary"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    account_id = getattr(settings, "CLOUDFLARE_R2_ACCOUNT_ID", "") or getattr(
        settings, "CLOUDFLARE_ACCOUNT_ID", ""
    )
    access_key = getattr(settings, "CLOUDFLARE_R2_ACCESS_KEY_ID", "")
    secret_key = getattr(settings, "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
    bucket = getattr(settings, "CLOUDFLARE_R2_BUCKET_NAME", "")

    if not all([account_id, access_key, secret_key, bucket]):
        return {}

    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

        prefix_totals: dict[str, dict] = {}
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                size: int = obj["Size"]
                # Top-level prefix is everything before the first "/"
                top = key.split("/")[0] if "/" in key else "_root"
                if top not in prefix_totals:
                    prefix_totals[top] = {"objects": 0, "bytes": 0}
                prefix_totals[top]["objects"] += 1
                prefix_totals[top]["bytes"] += size

        # Add human-readable GB and estimated cost (£0.015/GB/month)
        _GB = 1_073_741_824
        for _prefix, totals in prefix_totals.items():
            gb = round(totals["bytes"] / _GB, 3)
            totals["gb"] = gb
            totals["cost_gbp"] = round(gb * 0.015, 4)

        cache.set(cache_key, prefix_totals, 3600)  # 1 hour
        return prefix_totals

    except Exception as exc:
        logger.warning("R2 storage summary failed: %s", exc)
        return {}
