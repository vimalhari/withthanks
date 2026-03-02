import os
import time
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


# def send_video_email(
#     to_email: str,
#     file_path: str,
#     subject: Optional[str] = None,
#     html: Optional[str] = None,
#     from_email: Optional[str] = None,
# ) -> Dict[str, Any]:
#     """
#     Send a thank-you video email to a donor with a download link.

#     Args:
#         to_email: Recipient email address.
#         file_path: Path to the video file (used to verify existence and get filename).
#         subject: Optional custom subject line.
#         html: Optional HTML message body.
#         from_email: Optional sender address (defaults to Django's DEFAULT_FROM_EMAIL).

#     Returns:
#         A dictionary containing the Resend API response.

#     Raises:
#         FileNotFoundError: If the video file does not exist.
#         ValueError: If email validation fails.
#         RuntimeError: If sender or API key is not configured.
#         Exception: If the API call fails.
#     """
#     _ensure_api_key()

#     sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
#     if not sender:
#         raise RuntimeError("No sender configured — set DEFAULT_FROM_EMAIL or pass 'from_email'.")

#     recipient = _normalize_email(to_email)
#     file = Path(file_path)

#     if not file.exists() or not file.is_file():
#         raise FileNotFoundError(f"Video file not found: {file}")

#     # Construct the public video URL
#     # The file is stored at: /home/rankraze/uploads/video-generation/uploads/
#     # URL format: http://SERVER_IP:PORT/media/outputs/FILENAME
#     server_url = getattr(settings, "SERVER_BASE_URL", "http://14.194.141.164:8000")
#     video_filename = file.name
#     video_url = f"{server_url}/media/outputs/{video_filename}"

#     # Default email content with download link
#     subject = subject or "Thank You for Your Donation ❤️"
#     html = (
#         html
#         or f"""
#         <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
#             <h2 style="color: #2c5aa0;">Thank You for Your Generous Donation!</h2>
#             <p>Dear supporter,</p>
#             <p>We deeply appreciate your contribution. We've created a personalized video message
#             to express our heartfelt gratitude for your support.</p>
            
#             <div style="text-align: center; margin: 30px 0;">
#                 <a href="{video_url}" 
#                    style="background-color: #2c5aa0; 
#                           color: white; 
#                           padding: 15px 30px; 
#                           text-decoration: none; 
#                           border-radius: 5px; 
#                           font-weight: bold;
#                           display: inline-block;">
#                     🎥 View Your Thank You Video
#                 </a>
#             </div>
            
#             <p style="font-size: 12px; color: #666;">
#                 If the button doesn't work, copy and paste this link into your browser:<br>
#                 <a href="{video_url}" style="color: #2c5aa0;">{video_url}</a>
#             </p>
            
#             <p>Warm regards,<br><strong>The Charity Team</strong></p>
#         </div>
#         """
#     )

#     params = {
#         "from": sender,
#         "to": recipient,
#         "subject": subject,
#         "html": html,
#     }

#     try:
#         response = resend.Emails.send(params)
#         email_id = response.get("id")
#         logger.info("✅ Sent thank-you video link to %s [Resend ID: %s] [Video URL: %s]", recipient, email_id, video_url)
#         return response
#     except Exception as e:
#         logger.exception("❌ Failed to send video email to %s: %s", recipient, e)
#         raise


def send_video_email(
    to_email: str,
    file_path: Optional[str],
    job_id: str,
    donor_name: str = "Donor",
    donation_amount: str = "0",
    organization_name: str = "WithThanks",
    subject: Optional[str] = None,
    html: Optional[str] = None,
    from_email: Optional[str] = None,
    is_card_only: bool = False,
) -> Dict[str, Any]:

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
            is_card_only = True
            file = None
    else:
        is_card_only = True

    server_url = getattr(settings, "SERVER_BASE_URL", "https://hirefella.com")

    video_url = ""
    if file:
        try:
             # Calculate relative path from MEDIA_ROOT to support any subdirectory (outputs, clients, etc)
             rel_path = os.path.relpath(file, settings.MEDIA_ROOT)
             clean_rel_path = rel_path.replace("\\", "/")
             video_url = f"{server_url}{settings.MEDIA_URL}{clean_rel_path}".replace("//", "/")
             
             # Double check server_url doesn't double slash with MEDIA_URL if MEDIA_URL is just /media/
             # Simple robust construction:
             s_url = server_url.rstrip("/")
             m_url = settings.MEDIA_URL.strip("/")
             video_url = f"{s_url}/{m_url}/{clean_rel_path}"
        except ValueError:
             # Fallback if file is not inside MEDIA_ROOT (e.g. temp dir)
             video_url = f"{server_url}/media/outputs/{file.name}"

    tracking_pixel_url = f"{server_url}/track/email/{job_id}/"
    unsubscribe_url = f"{server_url}/charity/unsubscribe/{job_id}/"

    # SIMPLE SaaS TEMPLATE
    subject = subject or ("Thank You Card" if is_card_only else "Personalized thank-you message")
    
    if not html:
        # CTA Logic (Only if HTML is NOT provided)
        if is_card_only:
            is_image = False
            filename = file.name.lower() if file else ""
            if filename.endswith(('.png', '.jpg', '.jpeg', '.gif')):
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
            
            is_image_ext = file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
            if is_image_ext and html and video_url in html:
                 # The HTML references the video_url. We should swap it for cid:
                 # This makes localhost testing work perfectly as the image is embedded.
                 cid_id = f"image-{file.name}"
                 params["html"] = html.replace(video_url, f"cid:{cid_id}")
                 
                 params["attachments"] = [
                    {
                        "filename": file.name,
                        "content": file_content,
                        "content_id": cid_id, # This makes it inline!
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
            logger.info(f"Skipping attachment for {file.name} ({file_size} bytes) - too large for Resend. Link only.")

    try:
        # Increase timeout or add retry logic if needed. 
        # resend-python doesn't expose timeout easily in the top-level send call, 
        # but we can wrap it in a retry loop.
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = resend.Emails.send(params)
                logger.info(
                    "📩 Email sent to %s | Video: %s | Pixel: %s (Attempt %s)",
                    recipient, video_url, tracking_pixel_url, attempt + 1
                )
                return response
            except Exception as exc:
                last_error = exc
                logger.warning(f"Resend attempt {attempt + 1} failed: {exc}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt) # Exponential backoff
        
        raise last_error

    except Exception as e:
        logger.exception("Failed to send video email to %s: %s", recipient, e)
        raise


def send_invoice_email(
    to_email: str,
    invoice_pdf_bytes: bytes,
    invoice_number: str,
    invoice_id: Optional[str] = None,
    subject: Optional[str] = None,
    html: Optional[str] = None,
    from_email: Optional[str] = None,
    filename: str = "invoice.pdf"
) -> Dict[str, Any]:
    """
    Send an invoice PDF via email.
    
    Args:
        to_email: Recipient email address.
        invoice_pdf_bytes: The PDF content as bytes.
        invoice_number: The invoice number for display.
        invoice_id: Optional UUID for tracking opens.
        subject: Optional custom subject.
        html: Optional custom HTML body.
        from_email: Optional sender address.
        filename: Filename for the attachment.
        
    Returns:
        Resend API response.
    """
    _ensure_api_key()

    sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if not sender:
        raise RuntimeError("No sender configured — set DEFAULT_FROM_EMAIL or pass 'from_email'.")

    recipient = _normalize_email(to_email)
    
    # Default Subject
    if not subject:
        subject = f"Invoice {invoice_number} from WithThanks"
        
    # Default HTML
    if not html:
        tracking_pixel_url = ""
        if invoice_id:
            server_url = getattr(settings, "SERVER_BASE_URL", "https://hirefella.com")
            tracking_pixel_url = f"{server_url}/track/invoice/{invoice_id}/"

        html = f"""
        <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
            <h2>Invoice {invoice_number}</h2>
            <p>Hello,</p>
            <p>Please find attached invoice <strong>{invoice_number}</strong>.</p>
            <p>Thank you for your business.</p>
            
            <p>Warm regards,<br><strong>WithThanks Team</strong></p>
            {f'<img src="{tracking_pixel_url}" width="1" height="1" style="display:none;" />' if tracking_pixel_url else ''}
        </div>
        """

    # Prepare Attachment
    # Encode bytes to base64 string
    pdf_b64 = base64.b64encode(invoice_pdf_bytes).decode("utf-8")
    
    params = {
        "from": sender,
        "to": recipient,
        "subject": subject,
        "html": html,
        "attachments": [
            {
                "filename": filename,
                "content": pdf_b64,
            }
        ]
    }

    try:
        response = resend.Emails.send(params)
        logger.info("✅ Sent invoice %s to %s [Resend ID: %s]", invoice_number, recipient, response.get("id"))
        return response
    except Exception as e:
        logger.exception("❌ Failed to send invoice to %s: %s", recipient, e)
        raise
