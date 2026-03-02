import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import redirect, render

from .models import Campaign, Charity, DonationJob
from .utils.access_control import get_active_charity
from .views_admin import (  # noqa: F401
    api_campaigns,
    api_clients,
    clear_client_context,
    client_create_view,
    client_setup_view,
    manage_user_password,
    remove_member,
    switch_client,
)
from .views_auth import (  # noqa: F401
    change_password,
    login_view,
    logout_view,
    profile_view,
    register_view,
)
from .views_automation import (  # noqa: F401
    favicon_view,
    robots_view,
    track_click_view,
    track_invoice_open,
    track_open_view,
    track_unsubscribe_full_view,
    track_video_event_view,
    video_landing_view,
)
from .views_batches import (  # noqa: F401
    batch_detail_view,
    batch_tracking_report,
    export_donation_report,
    send_email_wizard,
    upload_csv_and_process,
)
from .views_invoices import (  # noqa: F401
    create_invoice_view,
    invoice_detail_view,
    invoice_edit_view,
    invoice_export_csv,
    invoice_export_json,
    invoice_export_pdf,
    invoice_mark_paid,
    invoice_send_email,
    invoice_stripe_send,
    invoice_void,
    invoices_view,
)

# All names below are intentional re-exports consumed by urls.py via `views.<name>`.
__all__ = [
    # views_admin
    "api_campaigns",
    "api_clients",
    "clear_client_context",
    "client_create_view",
    "client_setup_view",
    "manage_user_password",
    "remove_member",
    "switch_client",
    # views_auth
    "change_password",
    "login_view",
    "logout_view",
    "profile_view",
    "register_view",
    # views_automation
    "favicon_view",
    "robots_view",
    "track_click_view",
    "track_invoice_open",
    "track_open_view",
    "track_unsubscribe_full_view",
    "track_video_event_view",
    "video_landing_view",
    # views_batches
    "batch_detail_view",
    "batch_tracking_report",
    "export_donation_report",
    "send_email_wizard",
    "upload_csv_and_process",
    # views_invoices
    "create_invoice_view",
    "invoice_detail_view",
    "invoice_edit_view",
    "invoice_export_csv",
    "invoice_export_json",
    "invoice_export_pdf",
    "invoice_mark_paid",
    "invoice_send_email",
    "invoice_stripe_send",
    "invoice_void",
    "invoices_view",
    # local
    "dashboard_view",
    "logs_view",
]

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
