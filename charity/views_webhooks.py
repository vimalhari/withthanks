import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .analytics_models import CampaignStats, VideoEvent
from .models import Campaign, DonationJob

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


class StripeWebhookView(View):
    """
    Handles webhooks from Stripe for invoice payment lifecycle events.

    Configure the endpoint in Stripe Dashboard → Developers → Webhooks:
      URL: https://yourdomain.com/charity/webhooks/stripe/
      Events: invoice.paid, invoice.payment_failed, invoice.finalized
    """

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, *args, **kwargs):
        from .services.stripe_service import handle_webhook_event, is_enabled

        if not is_enabled():
            return JsonResponse({"error": "Stripe is not enabled"}, status=503)

        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        if not sig_header:
            return HttpResponse(status=400)

        try:
            result = handle_webhook_event(request.body, sig_header)
            return JsonResponse(result)
        except Exception as exc:
            logger.error(f"Stripe webhook error: {exc}")
            return HttpResponse(status=400)
