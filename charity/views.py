import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import redirect, render

from .models import Campaign, Charity, DonationJob
from .utils.access_control import get_active_charity
from .views_admin import *  # noqa: F403

# Hub Imports for backward compatibility with urls.py
from .views_auth import *  # noqa: F403
from .views_automation import *  # noqa: F403
from .views_batches import *  # noqa: F403
from .views_invoices import *  # noqa: F403

logger = logging.getLogger(__name__)


@login_required(login_url="charity_login")
def dashboard_view(request):
    """Core dashboard with performance optimizations."""
    current_charity = get_active_charity(request)
    if not current_charity and not request.user.is_superuser:
        return redirect("client_setup")

    view_mode = request.GET.get("view", "campaigns")
    # Base query optimized with select_related
    jobs = DonationJob.objects.all().select_related("donation_batch", "donation_batch__charity")
    if current_charity:
        jobs = jobs.filter(donation_batch__charity=current_charity)

    # Simple stats for summary
    stats = jobs.aggregate(
        total=Count("id"),
        success=Count("id", filter=Q(status="success")),
        failed=Count("id", filter=Q(status="failed")),
        pending=Count("id", filter=Q(status="pending")),
    )

    # List population based on view mode
    if view_mode == "campaigns":
        clients = (
            Campaign.objects.filter(client=current_charity)
            if current_charity
            else Campaign.objects.all()
        )
        # Optimization: annotate with stats if needed by template
        clients = clients.annotate(
            total_batches=Count("batches", distinct=True),
            total_videos=Count("batches__jobs", distinct=True),
        ).select_related("client")
    elif request.user.is_superuser and view_mode == "clients":
        clients = (
            Charity.objects.all()
            .annotate(
                total_campaigns=Count("campaigns", distinct=True),
                total_batches=Count("batches", distinct=True),
                total_videos=Count("batches__jobs", distinct=True),
            )
            .order_by("client_name")
        )
    else:
        clients = [current_charity] if current_charity else []

    return render(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "clients": clients,
            "view_mode": view_mode,
            "current_charity": current_charity,
        },
    )


@login_required(login_url="charity_login")
def logs_view(request):
    """Paginated logs view."""
    current_charity = get_active_charity(request)
    jobs_list = DonationJob.objects.filter(donation_batch__charity=current_charity).order_by(
        "-created_at"
    )
    paginator = Paginator(jobs_list, 25)
    logs = paginator.get_page(request.GET.get("page"))
    return render(request, "logs.html", {"logs": logs, "current_charity": current_charity})
