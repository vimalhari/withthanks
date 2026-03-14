import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .analytics_models import EmailEvent, VideoEvent
from .models import DonationBatch
from .utils.access_control import get_active_charity


@login_required(login_url="charity_login")
def batch_detail_view(request, batch_id):
    """Detailed stats for a specific batch."""
    current_charity = get_active_charity(request)
    if request.user.is_superuser and not current_charity:
        batch = get_object_or_404(DonationBatch, id=batch_id)
    else:
        batch = get_object_or_404(DonationBatch, id=batch_id, charity=current_charity)

    jobs = batch.jobs.all()
    stats = jobs.aggregate(
        total_real=Sum("real_views"),
        total_videos=Count("id"),
        success_count=Count("id", filter=Q(status="success")),
    )

    video_events = VideoEvent.objects.filter(job__donation_batch=batch)
    _engagement = video_events.aggregate(
        total_plays=Count("id", filter=Q(event_type="PLAY")),
        completions=Count("id", filter=Q(event_type="COMPLETE")),
    )

    email_events = EmailEvent.objects.filter(job__donation_batch=batch)
    delivery_breakdown = email_events.values("event_type").annotate(count=Count("id"))
    bounced_logs = email_events.filter(event_type="BOUNCED").select_related("job")

    daily_sent = (
        email_events.filter(event_type="SENT")
        .annotate(date=TruncDate("timestamp"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )
    chart_data = {
        "labels": [d["date"].strftime("%Y-%m-%d") for d in daily_sent],
        "sent": [d["count"] for d in daily_sent],
    }

    return render(
        request,
        "batch_report.html",
        {
            "batch": batch,
            "stats": stats,
            "jobs": jobs,
            "bounced_logs": bounced_logs,
            "delivery_breakdown": list(delivery_breakdown),
            "chart_data": json.dumps(chart_data),
        },
    )


@login_required(login_url="charity_login")
def batch_tracking_report(request, batch_id):
    """API to return JSON report for a batch."""
    from .models import EmailTracking

    current_charity = get_active_charity(request)
    if request.user.is_superuser and not current_charity:
        batch = get_object_or_404(DonationBatch, id=batch_id)
    else:
        batch = get_object_or_404(DonationBatch, id=batch_id, charity=current_charity)

    stats = EmailTracking.objects.filter(batch=batch).aggregate(
        total_sent=Count("id"),
        opened_count=Count("id", filter=Q(opened=True)),
        clicked_count=Count("id", filter=Q(clicked=True)),
    )
    return JsonResponse(stats)
