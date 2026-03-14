from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .views_admin import (
    api_campaigns,
    api_charities,
    clear_charity_context,
    switch_charity,
)
from .views_auth import (
    login_view,
    logout_view,
)
from .views_batch import batch_detail_view, batch_tracking_report
from .views_invoice_actions import (
    invoice_mark_paid,
    invoice_send_email,
    invoice_void,
)
from .views_invoice_exports import (
    invoice_export_csv,
    invoice_export_json,
    invoice_export_pdf,
)
from .views_invoices import (
    create_invoice_view,
    invoice_detail_view,
    invoice_edit_view,
    invoices_view,
)
from .views_tracking import (
    favicon_view,
    robots_view,
    track_click_view,
    track_invoice_open,
    track_open_view,
    track_unsubscribe_full_view,
    track_video_event_view,
    video_landing_view,
)

# All names below are intentional re-exports consumed by urls.py via `views.<name>`.
__all__ = [  # noqa: RUF022
    # views_admin
    "api_campaigns",
    "api_charities",
    "clear_charity_context",
    "switch_charity",
    # views_auth
    "login_view",
    "logout_view",
    # views_tracking
    "favicon_view",
    "robots_view",
    "track_click_view",
    "track_invoice_open",
    "track_open_view",
    "track_unsubscribe_full_view",
    "track_video_event_view",
    "video_landing_view",
    # views_batch
    "batch_detail_view",
    "batch_tracking_report",
    # views_invoices
    "create_invoice_view",
    "invoice_detail_view",
    "invoice_edit_view",
    "invoice_export_csv",
    "invoice_export_json",
    "invoice_export_pdf",
    "invoice_mark_paid",
    "invoice_send_email",
    "invoice_void",
    "invoices_view",
    # local
    "dashboard_view",
]


@login_required(login_url="charity_login")
def dashboard_view(request):
    """Keep legacy dashboard URLs alive while landing users on reports."""
    return redirect("analytics_home")
