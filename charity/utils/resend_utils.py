import base64
import logging
import os
from email.utils import parseaddr
from pathlib import Path
from typing import Any

import resend
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_STREAM_HTML = """
<div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
  <h2 style="color: #222;">Thank You for Your Generous Donation! &#10084;&#65039;</h2>
  <p>Dear supporter,</p>
  <p>We have a personal video message for you. Click the image below to watch it:</p>
  <a href="{playback_url}" target="_blank"
     style="display: block; text-align: center; margin: 24px 0; text-decoration: none;">
    <img src="{thumbnail_url}"
         alt="Watch your thank you video"
         style="max-width: 100%; border-radius: 8px;
                box-shadow: 0 4px 16px rgba(0,0,0,0.18);" />
    <div style="margin-top: 14px; display: inline-block; background: #d63384;
                color: #fff; padding: 13px 28px; border-radius: 6px;
                font-weight: bold; font-size: 16px; letter-spacing: 0.3px;">
      &#9654;&nbsp; Watch Your Thank You Video
    </div>
  </a>
  <p style="color: #666; font-size: 13px;">
    If the button above does not work, copy and paste this link into your browser:<br>
    <a href="{playback_url}" style="color: #d63384;">{playback_url}</a>
  </p>
  <p>Warm regards,<br><strong>The Charity Team</strong></p>
</div>
"""

_ATTACHMENT_HTML = """
<div style="font-family: Arial, sans-serif; color: #333;">
    <h2>Thank You for Your Generous Donation!</h2>
    <p>Dear supporter,</p>
    <p>We deeply appreciate your contribution. Please find attached a short video message
    from our team expressing our gratitude for your support.</p>
    <p>Warm regards,<br><strong>The Charity Team</strong></p>
</div>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_api_key() -> None:
    """
    Ensure that the Resend API key is loaded from environment or Django settings.
    Raises a RuntimeError if not found.
    """
    key = os.environ.get("RESEND_API_KEY") or getattr(settings, "RESEND_API_KEY", None)
    if not key:
        raise RuntimeError("❌ RESEND_API_KEY not found in environment or settings.")
    resend.api_key = key


def _normalize_email(email: str) -> str:
    """
    Validate and normalize an email address.

    Args:
        email: The email address to normalize.

    Returns:
        The cleaned email address.

    Raises:
        ValueError: If the email is invalid or empty.
    """
    if not email:
        raise ValueError("Email address cannot be empty.")

    _, addr = parseaddr(email.strip())
    if addr and "@" in addr:
        return addr

    raise ValueError(f"Invalid email address: {email}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def send_video_email(
    to_email: str,
    *,
    file_path: str = "",
    playback_url: str = "",
    thumbnail_url: str = "",
    subject: str | None = None,
    html: str | None = None,
    from_email: str | None = None,
) -> dict[str, Any]:
    """Send a thank-you video email to a donor using the Resend API.

    When *playback_url* is supplied (Cloudflare Stream), the video is **not**
    attached – instead the email contains a clickable thumbnail that opens the
    hosted player.  This keeps email size small and enables view-tracking via
    Cloudflare.

    When *playback_url* is empty the function falls back to attaching the raw
    MP4 from *file_path* (original behaviour).

    Args:
        to_email:      Recipient email address.
        file_path:     Local path to the video file (used only in fallback mode).
        playback_url:  Cloudflare Stream player URL.
        thumbnail_url: Cloudflare Stream auto-thumbnail URL.
        subject:       Optional custom subject line.
        html:          Optional HTML body (overrides auto-generated content).
        from_email:    Optional sender address.

    Returns:
        Resend API response dict.

    Raises:
        FileNotFoundError: If attachment mode is used and *file_path* is absent.
        ValueError:        If email validation fails.
        RuntimeError:      If sender or API key is not configured.
    """
    _ensure_api_key()

    sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not sender:
        raise RuntimeError("No sender configured — set DEFAULT_FROM_EMAIL or pass 'from_email'.")

    recipient = _normalize_email(to_email)
    subject = subject or "Thank You for Your Donation ❤️"
    use_stream = bool(playback_url)

    if use_stream:
        # --- Cloudflare Stream path: thumbnail + link, no attachment ----------
        body = html or _STREAM_HTML.format(
            playback_url=playback_url,
            thumbnail_url=thumbnail_url or playback_url,
        )
        params: dict[str, Any] = {
            "from": sender,
            "to": recipient,
            "subject": subject,
            "html": body,
        }
        logger.debug("Sending stream-link email to %s  player=%s", recipient, playback_url)
    else:
        # --- Fallback: attach raw MP4 -----------------------------------------
        file = Path(file_path)
        if not file.exists() or not file.is_file():
            raise FileNotFoundError(f"Attachment not found: {file}")

        try:
            with open(file, "rb") as f:
                b64_content = base64.b64encode(f.read()).decode("ascii")
        except Exception as e:
            logger.error("Failed to read or encode video file %s: %s", file, e)
            raise

        body = html or _ATTACHMENT_HTML
        params = {
            "from": sender,
            "to": recipient,
            "subject": subject,
            "html": body,
            "attachments": [
                {"filename": file.name, "content": b64_content, "type": "video/mp4"},
            ],
        }
        logger.debug("Sending attachment email to %s  file=%s", recipient, file)

    try:
        response = resend.Emails.send(params)
        email_id = response.get("id")
        logger.info("✅ Sent thank-you video to %s [Resend ID: %s]", recipient, email_id)
        return response
    except Exception as e:
        logger.exception("❌ Failed to send video email to %s: %s", recipient, e)
        raise

