import os
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from email.utils import parseaddr

import resend
from django.conf import settings

logger = logging.getLogger(__name__)


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

    name, addr = parseaddr(email.strip())
    if addr and "@" in addr:
        return addr

    raise ValueError(f"Invalid email address: {email}")


def send_video_email(
    to_email: str,
    file_path: str,
    subject: Optional[str] = None,
    html: Optional[str] = None,
    from_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a thank-you video email to a donor using the Resend API.

    Args:
        to_email: Recipient email address.
        file_path: Path to the video file (e.g., a generated thank-you message).
        subject: Optional custom subject line.
        html: Optional HTML message body.
        from_email: Optional sender address (defaults to Django's DEFAULT_FROM_EMAIL).

    Returns:
        A dictionary containing the Resend API response.

    Raises:
        FileNotFoundError: If the video file does not exist.
        ValueError: If email validation fails.
        RuntimeError: If sender or API key is not configured.
        Exception: If the API call fails.
    """
    _ensure_api_key()

    sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not sender:
        raise RuntimeError("No sender configured — set DEFAULT_FROM_EMAIL or pass 'from_email'.")

    recipient = _normalize_email(to_email)
    file = Path(file_path)

    if not file.exists() or not file.is_file():
        raise FileNotFoundError(f"Attachment not found: {file}")

    # Default email content
    subject = subject or "Thank You for Your Donation ❤️"
    html = (
        html
        or f"""
        <div style="font-family: Arial, sans-serif; color: #333;">
            <h2>Thank You for Your Generous Donation!</h2>
            <p>Dear supporter,</p>
            <p>We deeply appreciate your contribution. Please find attached a short video message
            from our team expressing our gratitude for your support.</p>
            <p>Warm regards,<br><strong>The Charity Team</strong></p>
        </div>
        """
    )

    # Encode video file to Base64
    try:
        with open(file, "rb") as f:
            b64_content = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        logger.error("Failed to read or encode video file %s: %s", file, e)
        raise

    params = {
        "from": sender,
        "to": recipient,
        "subject": subject,
        "html": html,
        "attachments": [
            {"filename": file.name, "content": b64_content, "type": "video/mp4"},
        ],
    }

    try:
        response = resend.Emails.send(params)
        email_id = response.get("id")
        logger.info("✅ Sent thank-you video to %s [Resend ID: %s]", recipient, email_id)
        return response
    except Exception as e:
        logger.exception("❌ Failed to send video email to %s: %s", recipient, e)
        raise
