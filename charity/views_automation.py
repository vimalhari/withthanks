import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import DonationJob, EmailTracking, Invoice, UnsubscribedUser
from .models_analytics import EmailEvent, VideoEvent

logger = logging.getLogger(__name__)


def favicon_view(request):
    return HttpResponse(status=204)


def robots_view(request):
    content = "User-agent: *\nDisallow: /admin/\n"
    return HttpResponse(content, content_type="text/plain")


def track_open_view(request):
    """Tracks email opens via 1x1 pixel using EmailTracking model."""
    try:
        user_id = request.GET.get("u")
        if user_id:
            tracking = EmailTracking.objects.filter(job_id=user_id).first()
            if tracking and not tracking.opened:
                tracking.opened = True
                tracking.open_time = timezone.now()
                tracking.save(update_fields=["opened", "open_time"])
                job = tracking.job
                if job:
                    job.real_views += 1
                    job.save(update_fields=["real_views"])
                    EmailEvent.objects.create(campaign=job.campaign, job=job, event_type="OPEN")
    except Exception as e:
        logger.error(f"Tracking Open Error: {e}")

    pixel = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x08\xd76\xcf\xb7\r\x00\x00\x00\x82\x00\x81\r\n\x00\x00\x00\x00IEND\xaeB`\x82"
    return HttpResponse(pixel, content_type="image/png")


def track_click_view(request):
    """Tracks link clicks and redirects to destination."""
    user_id = request.GET.get("u")
    redirect_url = "/"
    try:
        if user_id:
            tracking = EmailTracking.objects.filter(job_id=user_id).first()
            if tracking and not tracking.clicked:
                tracking.clicked = True
                tracking.click_time = timezone.now()
                tracking.save(update_fields=["clicked", "click_time"])
                job = tracking.job
                if job:
                    job.real_clicks += 1
                    job.save(update_fields=["real_clicks"])
                    EmailEvent.objects.create(campaign=job.campaign, job=job, event_type="CLICK")
                    v_url = job.video_url
                    if v_url and v_url.lower().split("?")[0].endswith((".mp4", ".mov", ".avi")):
                        server_url = getattr(
                            settings, "SERVER_BASE_URL", "https://hirefella.com"
                        ).rstrip("/")
                        redirect_path = reverse("video_landing", args=[job.id])
                        redirect_url = f"{server_url}{redirect_path}"
                    elif v_url:
                        redirect_url = v_url
    except Exception as e:
        logger.error(f"Tracking Click Error: {e}")
    return redirect(redirect_url)


def track_unsubscribe_full_view(request):
    """Handles deep unsubscribe requests with context."""
    user_id = request.GET.get("u")
    context = {"success": False}
    if user_id:
        try:
            tracking = EmailTracking.objects.filter(job_id=user_id).first()
            if tracking:
                job = tracking.job
                campaign = job.campaign if job else None

                # Check if it's VDM. If not, don't process unsubscribes
                is_vdm = False
                if tracking.appeal_type == "VDM" or (campaign and campaign.appeal_type == "VDM"):
                    is_vdm = True

                if not is_vdm:
                    # Ignore unsubscribe request for non-VDM emails
                    return render(
                        request,
                        "unsubscribe.html",
                        {
                            "success": False,
                            "error": "Unsubscribe is only available for marketing communications.",
                        },
                    )

                tracking.unsubscribed = True
                tracking.vdm = True
                tracking.save(update_fields=["unsubscribed", "vdm"])

                if job:
                    UnsubscribedUser.objects.get_or_create(
                        email=job.email,
                        charity=job.charity,
                        defaults={
                            "reason": "Clicked unsubscribe link",
                            "unsubscribed_from_job": job,
                        },
                    )
                    EmailEvent.objects.create(campaign=campaign, job=job, event_type="UNSUB")

                context["success"] = True
        except Exception as e:
            logger.error(f"Tracking Unsubscribe Error: {e}")
    return render(request, "unsubscribe.html", context)


def track_invoice_open(request, invoice_id):
    """AUDIT FIX: Safely record invoice open event."""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        if not invoice.email_opened_at:
            invoice.email_opened_at = timezone.now()
            invoice.save(update_fields=["email_opened_at"])
    except Exception as e:
        logger.warning(f"track_invoice_open: could not record open for invoice {invoice_id}: {e}")
    pixel = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT\x08\xd76\xcf\xb7\r\x00\x00\x00\x82\x00\x81\r\n\x00\x00\x00\x00IEND\xaeB`\x82"
    return HttpResponse(pixel, content_type="image/png")


def video_landing_view(request, job_id):
    """Displays the video landing page with engagement tracking."""
    job = get_object_or_404(DonationJob, id=job_id)
    video_url = job.video_url
    if not video_url:
        return redirect("/")
    # Resolve the EmailTracking record so the JS player can send watch events
    tracking = EmailTracking.objects.filter(job=job).first()
    tracking_id = str(tracking.id) if tracking else ""
    return render(
        request,
        "video_landing.html",
        {"job": job, "video_url": video_url, "tracking_id": tracking_id},
    )


def track_video_event_view(request):
    """AJAX endpoint for video play/progress/complete."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            tracking_id = data.get("tracking_id")
            event = data.get("event")
            duration = data.get("duration", 0)
            if tracking_id:
                tracking = EmailTracking.objects.filter(id=tracking_id).first()
                if tracking:
                    upd = []
                    job = tracking.job
                    if event == "play" and not tracking.video_played:
                        tracking.video_played = True
                        tracking.video_started_at = timezone.now()
                        upd.extend(["video_played", "video_started_at"])
                        if job:
                            VideoEvent.objects.create(
                                campaign=job.campaign, job=job, event_type="PLAY"
                            )
                    elif (
                        event in ["progress", "pause"] and duration > tracking.video_watch_duration
                    ):
                        tracking.video_watch_duration = int(duration)
                        upd.append("video_watch_duration")
                    elif event == "complete" and not tracking.video_completed:
                        tracking.video_completed = True
                        tracking.video_completed_at = timezone.now()
                        upd.extend(["video_completed", "video_completed_at"])
                        if job:
                            VideoEvent.objects.create(
                                campaign=job.campaign, job=job, event_type="COMPLETE"
                            )
                    if upd:
                        tracking.save(update_fields=upd)
            return JsonResponse({"status": "ok"})
        except Exception as e:
            logger.error(f"Video Event Tracking Error: {e}")
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"status": "invalid_method"}, status=405)
