from django.urls import path

from . import views, views_billing, views_crm, views_revenue, views_webhooks
from .views_admin import (
    api_campaigns,
    api_clients,
    clear_client_context,
    switch_client,
)

# No app_name to keep global namespace for now

urlpatterns = [
    path("", views.dashboard_view, name="charity_home"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("export-csv/", views.export_donation_report, name="export_csv"),
    path("upload-csv/", views.upload_csv_and_process, name="upload_csv"),
    path("login/", views.login_view, name="charity_login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("email/open/<int:job_id>.png", views.track_open_view, name="email_open_tracking"),
    path("track/email/<int:job_id>/", views.track_open_view, name="email_track_pixel"),
    # Tracking
    path("track/open/", views.track_open_view, name="track_open"),
    path("track/click/", views.track_click_view, name="track_click"),
    path("track/unsubscribe/", views.track_unsubscribe_full_view, name="track_unsubscribe_full"),
    path("track/invoice/<uuid:invoice_id>/", views.track_invoice_open, name="track_invoice_open"),
    path(
        "api/report/batch/<int:batch_id>/",
        views.batch_tracking_report,
        name="batch_tracking_report",
    ),
    # Video engagement
    path("track/video/event/", views.track_video_event_view, name="track_video_event"),
    path("watch/<int:job_id>/", views.video_landing_view, name="video_landing"),
    path("unsubscribe/<int:job_id>/", views.track_unsubscribe_full_view, name="unsubscribe"),
    path("logs/", views.logs_view, name="logs"),
    path("profile/", views.profile_view, name="profile"),
    path("change-password/", views.change_password, name="change_password"),
    # Client-switcher session helpers (superuser session context — not CRUD)
    path("api/clients/", api_clients, name="api_clients"),
    path("api/campaigns/", api_campaigns, name="api_campaigns"),
    path("switch-client/clear/", clear_client_context, name="clear_client_context"),
    path("switch-client/<int:charity_id>/", switch_client, name="switch_client"),
    # Batch reports
    path("reports/batch/<int:batch_id>/", views.batch_detail_view, name="batch_detail"),
    # Send wizard
    path("send/", views.send_email_wizard, name="send_email_wizard"),
    # Invoicing (custom wizard + exports + email actions)
    path("invoices/", views.invoices_view, name="invoices"),
    path("invoices/create/", views.create_invoice_view, name="create_invoice"),
    path("invoices/<uuid:invoice_id>/", views.invoice_detail_view, name="invoice_detail"),
    path("invoices/<uuid:invoice_id>/edit/", views.invoice_edit_view, name="invoice_edit"),
    path("invoices/<uuid:invoice_id>/pdf/", views.invoice_export_pdf, name="invoice_pdf"),
    path(
        "invoices/<uuid:invoice_id>/send-email/",
        views.invoice_send_email,
        name="invoice_send_email",
    ),
    path("invoices/<uuid:invoice_id>/csv/", views.invoice_export_csv, name="invoice_csv"),
    path("invoices/<uuid:invoice_id>/json/", views.invoice_export_json, name="invoice_json"),
    path(
        "invoices/<uuid:invoice_id>/mark-paid/", views.invoice_mark_paid, name="invoice_mark_paid"
    ),
    path("invoices/<uuid:invoice_id>/void/", views.invoice_void, name="invoice_void"),
    # Revenue intelligence
    path("api/revenue/", views_revenue.RevenueIntelligenceAPI.as_view(), name="api_revenue"),
    path("api/revenue/view/", views_revenue.revenue_dashboard_view, name="revenue_dashboard"),
    # Invoice calculation / creation APIs (used by invoice wizard)
    path(
        "api/billing/calculate/",
        views_billing.InvoiceCalculationAPI.as_view(),
        name="api_billing_calculate",
    ),
    path(
        "api/billing/create/", views_billing.CreateInvoiceAPI.as_view(), name="api_billing_create"
    ),
    # Webhooks
    path(
        "webhooks/cloudflare/",
        views_webhooks.CloudflareWebhookView.as_view(),
        name="cloudflare_webhook",
    ),
    path(
        "webhooks/resend/",
        views_webhooks.ResendWebhookView.as_view(),
        name="resend_webhook",
    ),
    # CRM integrations — Blackbaud Raiser's Edge NXT OAuth flow
    path("crm/blackbaud/connect/", views_crm.blackbaud_connect, name="blackbaud_connect"),
    path("crm/blackbaud/callback/", views_crm.blackbaud_callback, name="blackbaud_callback"),
    path("crm/blackbaud/disconnect/", views_crm.blackbaud_disconnect, name="blackbaud_disconnect"),
]
