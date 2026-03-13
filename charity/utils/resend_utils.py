import base64
import logging
import os
import time
from email.utils import parseaddr
from pathlib import Path
from typing import Any

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

    _, addr = parseaddr(email.strip())
    if addr and "@" in addr:
        return addr

    raise ValueError(f"Invalid email address: {email}")


def send_video_email(
    to_email: str,
    file_path: str | None,
    job_id: str,
    donor_name: str = "Donor",
    donation_amount: str = "0",
    organization_name: str = "WithThanks",
    subject: str | None = None,
    html: str | None = None,
    from_email: str | None = None,
    video_url: str | None = None,
    is_card_only: bool = False,
) -> dict[str, Any]:

    video_extensions = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}

    _ensure_api_key()

    sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not sender:
        raise RuntimeError("No sender configured — set DEFAULT_FROM_EMAIL or pass 'from_email'.")

    recipient = _normalize_email(to_email)

    file = None
    if file_path:
        file = Path(file_path)
        if not file.exists() or not file.is_file():
            logger.warning(f"Video file not found at {file_path}, falling back to card mode.")
            is_card_only = is_card_only or not video_url
            file = None
        elif file.suffix.lower() in video_extensions:
            logger.info(
                "Skipping local video attachment for %s; email delivery is link-only.", file
            )
            file = None
    else:
        is_card_only = is_card_only or not video_url

    server_url = getattr(settings, "SERVER_BASE_URL", "https://hirefella.com")

    # video_url is used only as a fallback when no custom HTML is supplied.
    video_url = video_url or ""

    tracking_pixel_url = f"{server_url}/track/email/{job_id}/"
    unsubscribe_url = f"{server_url}/charity/unsubscribe/{job_id}/"

    # SIMPLE SaaS TEMPLATE
    subject = subject or ("Thank You Card" if is_card_only else "Personalized thank-you message")

    if not html:
        # CTA Logic (Only if HTML is NOT provided)
        if is_card_only:
            is_image = False
            filename = file.name.lower() if file else ""
            if filename.endswith((".png", ".jpg", ".jpeg", ".gif")):
                is_image = True

            if is_image:
                # Image: Embed via public URL if available, or just as attachment.
                # For simplicity, if we have a public URL, we use it in the IMG tag.
                email_cta = f"""
                <div style="text-align: center; margin: 30px 0; padding: 20px; background-color: #f9f9f9; border: 1px solid #eee; border-radius: 8px;">
                    <p style="font-size: 16px; font-weight: bold; color: #333;">A Special Thank You ❤️</p>
                    <p style="font-size: 14px; color: #666; line-height: 1.5;">
                        We deeply appreciate your recent contribution. Please accept this digital thank-you card.
                    </p>
                    <div style="margin-top: 20px;">
                        <img src="{video_url}" alt="Gratitude Card" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    </div>
                </div>
                """
            else:
                # Video or No File
                email_cta = f"""
                <div style="text-align: center; margin: 30px 0; padding: 20px; background-color: #f9f9f9; border: 1px solid #eee; border-radius: 8px;">
                    <p style="font-size: 16px; font-weight: bold; color: #333;">Thank You Card ❤️</p>
                    <p style="font-size: 14px; color: #666; line-height: 1.5;">
                        We deeply appreciate your recent contribution. Since we sent you a personalized video message very recently,
                        please accept this digital thank-you card for your continued generosity.
                    </p>
                    <div style="font-size: 48px; margin: 20px 0;">📬✨</div>
                     <p style="font-size: 12px; color: #666;">
                        (If a video card is attached, please see below or <a href="{video_url}">click here</a>)
                    </p>
                </div>
                """
        else:
            email_cta = f"""
            <div style="text-align: center; margin: 30px 0;">
                <a href="{video_url}"
                   style="background-color: #000; color: #fff; padding: 15px 25px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                    🎥 View Your Video
                </a>
            </div>
            <p style="font-size: 11px; color: #666; text-align: center;">
                Video link: <a href="{video_url}">{video_url}</a>
            </p>
            """

        html = f"""
        <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
            <h2>Thank You, {donor_name}!</h2>
            <p><strong>Organization:</strong> {organization_name}</p>
            <p><strong>Donation Amount:</strong> {donation_amount}</p>
            <p>We deeply appreciate your support.</p>

            {email_cta}

            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee;">
                <p style="font-size: 11px; color: #999;">
                    If you no longer wish to receive these emails, you can
                    <a href="{unsubscribe_url}" style="color: #999;">unsubscribe here</a>.
                </p>
            </div>
            <img src="{tracking_pixel_url}" width="1" height="1" style="display:none;" />
        </div>
        """

    params = {
        "from": sender,
        "to": recipient,
        "subject": subject,
        "html": html,
    }

    if file:
        file_size = file.stat().st_size
        # Resend limit is 40MB total. Base64 encoding adds ~33% overhead.
        # 25MB * 1.33 = ~33.25MB, which is safe.
        if file_size < 15 * 1024 * 1024:
            with open(file, "rb") as f:
                file_content = base64.b64encode(f.read()).decode("utf-8")
            # Check if this file is being used as an image in the HTML logic we added (or template)
            # If the filename matches what we expect or we want to force inline:
            # For simplicity, if it's an image, let's treat it as inline if possible,
            # BUT we need to update the HTML to reference 'cid:filename'.

            is_image_ext = file.name.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))
            if is_image_ext and video_url and params["html"] and video_url in params["html"]:
                # The HTML references the video_url. We should swap it for cid:
                # This makes localhost testing work perfectly as the image is embedded.
                cid_id = f"image-{file.name}"
                params["html"] = params["html"].replace(video_url, f"cid:{cid_id}")

                params["attachments"] = [
                    {
                        "filename": file.name,
                        "content": file_content,
                        "content_id": cid_id,  # This makes it inline!
                    }
                ]
            else:
                # Standard attachment (Video or Image not in body)
                params["attachments"] = [
                    {
                        "filename": file.name,
                        "content": file_content,
                    }
                ]
        else:
            logger.info(
                f"Skipping attachment for {file.name} ({file_size} bytes) - too large for Resend. Link only."
            )

    try:
        # Increase timeout or add retry logic if needed.
        # resend-python doesn't expose timeout easily in the top-level send call,
        # but we can wrap it in a retry loop.

        max_retries = 3
        last_error: Exception = RuntimeError("All Resend send attempts failed")

        for attempt in range(max_retries):
            try:
                response = resend.Emails.send(params)
                logger.info(
                    "📩 Email sent to %s | Video: %s | Pixel: %s (Attempt %s)",
                    recipient,
                    video_url,
                    tracking_pixel_url,
                    attempt + 1,
                )
                return response
            except Exception as exc:
                last_error = exc
                logger.warning(f"Resend attempt {attempt + 1} failed: {exc}")
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)  # Exponential backoff

        raise last_error

    except Exception as e:
        logger.exception("Failed to send video email to %s: %s", recipient, e)
        raise


def _resolve_invoice_recipients(to_email: str | list[str]) -> list[str]:
    """Normalise *to_email* to a validated, non-empty list of addresses."""
    if isinstance(to_email, list):
        resolved = [_normalize_email(e) for e in to_email if e and e.strip()]
    else:
        resolved = [_normalize_email(to_email)]
    if not resolved:
        raise ValueError("No valid recipient email addresses provided.")
    return resolved


def _build_invoice_html(invoice_number: str, invoice_id: str | None) -> str:
    """Return a simple HTML email body for an invoice delivery."""
    tracking_pixel_url = ""
    if invoice_id:
        server_url = getattr(settings, "SERVER_BASE_URL", "https://hirefella.com")
        tracking_pixel_url = f"{server_url}/track/invoice/{invoice_id}/"

    pixel_tag = (
        f'<img src="{tracking_pixel_url}" width="1" height="1" style="display:none;" />'
        if tracking_pixel_url
        else ""
    )
    return f"""
        <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
            <h2>Invoice {invoice_number}</h2>
            <p>Hello,</p>
            <p>Please find attached invoice <strong>{invoice_number}</strong>.</p>
            <p>Thank you for your business.</p>
            <p>Warm regards,<br><strong>WithThanks Team</strong></p>
            {pixel_tag}
        </div>
        """


def send_invoice_email(
    to_email: str | list[str],
    invoice_pdf_bytes: bytes,
    invoice_number: str,
    invoice_id: str | None = None,
    subject: str | None = None,
    html: str | None = None,
    from_email: str | None = None,
    filename: str = "invoice.pdf",
) -> dict[str, Any]:
    """Send an invoice PDF to one or more recipients via Resend.

    *to_email* may be a single address string or a list; all addresses receive
    the same PDF in one API call.  Falls back to DEFAULT_FROM_EMAIL as sender.
    """
    _ensure_api_key()

    sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not sender:
        raise RuntimeError("No sender configured — set DEFAULT_FROM_EMAIL or pass 'from_email'.")

    recipients = _resolve_invoice_recipients(to_email)
    subject = subject or f"Invoice {invoice_number} from WithThanks"
    html = html or _build_invoice_html(invoice_number, invoice_id)

    pdf_b64 = base64.b64encode(invoice_pdf_bytes).decode("utf-8")

    params = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html,
        "attachments": [{"filename": filename, "content": pdf_b64}],
    }

    try:
        response = resend.Emails.send(params)
        logger.info(
            "✅ Sent invoice %s to %s [Resend ID: %s]",
            invoice_number,
            ", ".join(recipients),
            response.get("id"),
        )
        return response
    except Exception as e:
        logger.exception("❌ Failed to send invoice to %s: %s", recipients, e)
        raise
