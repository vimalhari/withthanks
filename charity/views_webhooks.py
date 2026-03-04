import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .analytics_models import CampaignStats, EmailEvent, VideoEvent
from .models import Campaign, DonationJob, EmailTracking

logger = logging.getLogger(__name__)


class CloudflareWebhookView(View):
    """
    Handles webhooks from Cloudflare Stream for video tracking.
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, *args, **kwargs):
        # 1. Validate Signature (if secret is configured)
        signature = request.headers.get("Webhook-Signature") or request.headers.get(
            "Cf-Webhook-Signature"
        )
        if settings.CLOUDFLARE_WEBHOOK_SECRET and not self.validate_signature(
            request.body, signature
        ):
            logger.warning("Invalid Cloudflare Webhook signature")
            return HttpResponse(status=401)

        try:
            data = json.loads(request.body)
            event_type = data.get("action")  # 'video.play', 'video.progress', etc.
            video_id = data.get("video_id")

            # Extract meta data (assuming passed during stream initiation)
            meta = data.get("meta", {})
            campaign_id = meta.get("campaign_id")
            user_id = meta.get("user_id")  # Job ID or External User ID

            # Map event type
            mapped_event = self.map_event_type(event_type)
            if not mapped_event:
                return JsonResponse({"status": "ignored_event"})

            # Extract metrics
            # Cloudflare sends 'playbackTime' and 'totalDuration' or similar in some events
            watch_duration = data.get("playback_time", 0.0)
            percentage = data.get("completion_percentage", 0.0)

            # If PROGRESS, we might get percentage
            if mapped_event == "COMPLETE":
                percentage = 100.0

            # 2. Store Event
            campaign = Campaign.objects.filter(id=campaign_id).first()
            job = DonationJob.objects.filter(id=user_id).first() if user_id else None

            event = VideoEvent.objects.create(
                campaign=campaign,
                user_id=user_id,
                job=job,
                event_type=mapped_event,
                watch_duration=watch_duration,
                completion_percentage=percentage,
                cloudflare_video_id=video_id,
            )

            # 3. Trigger Stats Update (In a real SaaSapp, this would be a Celery task)
            if campaign:
                stats, _ = CampaignStats.objects.get_or_create(campaign=campaign)
                stats.update_stats()

            return JsonResponse({"status": "success", "event_id": str(event.id)})

        except Exception as e:
            logger.error(f"Error processing Cloudflare Webhook: {e!s}")
            return JsonResponse({"error": str(e)}, status=400)

    def validate_signature(self, body, header):
        if not header:
            return False

        # Cloudflare format: time=TIMESTAMP; sig1=SIGNATURE
        try:
            parts = {p.split("=")[0]: p.split("=")[1] for p in header.split(";")}
            timestamp = parts.get("time")
            signature = parts.get("sig1")

            if not timestamp or not signature:
                return False

            # Verify signature: HMAC-SHA256(secret, timestamp + body)
            mac = hmac.new(
                settings.CLOUDFLARE_WEBHOOK_SECRET.encode("utf-8"),
                f"{timestamp}{body.decode('utf-8')}".encode(),
                hashlib.sha256,
            )
            return hmac.compare_digest(mac.hexdigest(), signature)
        except Exception as e:
            logger.warning(f"Webhook signature validation failed: {e}")
            return False

    def map_event_type(self, action):
        mapping = {
            "video.play": "PLAY",
            "video.progress": "PROGRESS",
            "video.completed": "COMPLETE",
        }
        return mapping.get(action)


class ResendWebhookView(View):
    """
    Handles inbound webhook events from Resend for all email activity:
    delivered, opened, clicked, bounced, complained, failed, suppressed.

    Resend sends a svix-signature header for verification.
    Configure RESEND_WEBHOOK_SECRET in .env and register this URL in the
    Resend dashboard: POST /webhooks/resend/
    """

    # Resend → EmailEvent mapping
    RESEND_EVENT_MAP = {
        "email.sent": "SENT",
        "email.delivered": "DELIVERED",
        "email.opened": "OPEN",
        "email.clicked": "CLICK",
        "email.bounced": "BOUNCED",
        "email.failed": "FAILED",
        "email.complained": "COMPLAINED",
        "email.suppressed": "SUPPRESSED",
    }

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, *args, **kwargs):
        # 1. Verify signature using svix headers
        if settings.RESEND_WEBHOOK_SECRET and not self._verify_signature(request):
            logger.warning("ResendWebhook: invalid signature")
            return HttpResponse(status=401)

        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        event_type = payload.get("type", "")
        data = payload.get("data", {})
        resend_email_id = data.get("email_id") or data.get("id", "")

        mapped_event = self.RESEND_EVENT_MAP.get(event_type)
        if not mapped_event:
            return JsonResponse({"status": "ignored", "type": event_type})

        # 2. Resolve DonationJob via resend_message_id
        job = None
        campaign = None
        if resend_email_id:
            job = DonationJob.objects.filter(resend_message_id=resend_email_id).first()
            if job:
                campaign = job.campaign

        # 3. Extract metadata
        ip_address = (data.get("click") or {}).get("ipAddress") or request.META.get("REMOTE_ADDR")
        user_agent = (data.get("click") or data.get("email") or {}).get("userAgent", "")
        timestamp = timezone.now()

        # 4. Write EmailEvent
        EmailEvent.objects.create(
            campaign=campaign,
            job=job,
            user_id=job.id if job else None,
            event_type=mapped_event,
            timestamp=timestamp,
            ip_address=ip_address if ip_address and ip_address != "unknown" else None,
            user_agent=user_agent or "",
        )

        # 5. Update EmailTracking flags
        if job:
            self._update_tracking(job, mapped_event, timestamp)

        # 6. Async CampaignStats refresh (fire and forget via Celery)
        if campaign:
            try:
                from .tasks import async_refresh_campaign_stats

                async_refresh_campaign_stats.delay(str(campaign.id))
            except Exception:
                pass  # Never block the webhook response for this

        logger.info("ResendWebhook: %s job=%s email_id=%s", mapped_event, job, resend_email_id)
        return JsonResponse({"status": "ok", "event": mapped_event})

    def _verify_signature(self, request) -> bool:
        """
        Verify Resend webhook signature using svix headers.
        See: https://resend.com/docs/dashboard/webhooks/verify-payload
        """
        try:
            svix_id = request.headers.get("svix-id", "")
            svix_timestamp = request.headers.get("svix-timestamp", "")
            svix_signature = request.headers.get("svix-signature", "")
            if not all([svix_id, svix_timestamp, svix_signature]):
                return False
            signed_content = f"{svix_id}.{svix_timestamp}.{request.body.decode('utf-8')}"
            secret = settings.RESEND_WEBHOOK_SECRET
            # Secret may be prefixed with "whsec_" — strip it
            if secret.startswith("whsec_"):
                import base64

                key = base64.b64decode(secret[6:])
            else:
                key = secret.encode("utf-8")
            expected = hmac.new(key, signed_content.encode("utf-8"), hashlib.sha256).digest()
            import base64 as _b64

            expected_b64 = _b64.b64encode(expected).decode()
            # svix-signature may be "v1,<sig>" or space-separated multiple
            for sig_part in svix_signature.split(" "):
                sig = sig_part.split(",", 1)[-1] if "," in sig_part else sig_part
                if hmac.compare_digest(sig, expected_b64):
                    return True
            return False
        except Exception as exc:
            logger.warning("ResendWebhook signature check error: %s", exc)
            return False

    def _update_tracking(self, job: DonationJob, event_type: str, timestamp) -> None:
        """Upsert EmailTracking flags based on the Resend event."""
        tracking, _ = EmailTracking.objects.get_or_create(
            job=job,
            defaults={
                "campaign": job.campaign,
                "batch": job.donation_batch,
                "user_id": job.id,
                "appeal_type": job.appeal_type or "WithThanks",
                "sent": True,
            },
        )
        update_fields = []
        if event_type == "OPEN" and not tracking.opened:
            tracking.opened = True
            tracking.open_time = timestamp
            update_fields += ["opened", "open_time"]
        elif event_type == "CLICK" and not tracking.clicked:
            tracking.clicked = True
            tracking.click_time = timestamp
            update_fields += ["clicked", "click_time"]
        elif event_type in ("BOUNCED", "FAILED", "SUPPRESSED") and not tracking.failed:
            tracking.failed = True
            update_fields.append("failed")
        elif event_type == "UNSUB" and not tracking.unsubscribed:
            tracking.unsubscribed = True
            update_fields.append("unsubscribed")
        if update_fields:
            tracking.save(update_fields=update_fields)
