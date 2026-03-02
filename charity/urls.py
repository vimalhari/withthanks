from django.urls import path

from . import views, views_billing, views_campaign, views_clients, views_revenue, views_webhooks

# No app_name to keep global namespace for now

urlpatterns = [
    path("", views.dashboard_view, name="charity_home"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("export-csv/", views.export_donation_report, name="export_csv"),
    path("upload-csv/", views.upload_csv_and_process, name="upload_csv"),
    path(
        "update-job-fake-views/<int:job_id>/",
        views.update_job_fake_views,
        name="update_job_fake_views",
    ),
    path("login/", views.login_view, name="charity_login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("email/open/<int:job_id>.png", views.track_open_view, name="email_open_tracking"),
    path("track/email/<int:job_id>/", views.track_open_view, name="email_track_pixel"),
    # NEW TRACKING SYSTEM
    path("track/open/", views.track_open_view, name="track_open"),
    path("track/click/", views.track_click_view, name="track_click"),
    path("track/unsubscribe/", views.track_unsubscribe_full_view, name="track_unsubscribe_full"),
    path("track/invoice/<uuid:invoice_id>/", views.track_invoice_open, name="track_invoice_open"),
    path(
        "api/report/batch/<int:batch_id>/",
        views.batch_tracking_report,
        name="batch_tracking_report",
    ),
    # VIDEO ENGAGEMENT
    path("track/video/event/", views.track_video_event_view, name="track_video_event"),
    path("watch/<uuid:job_id>/", views.video_landing_view, name="video_landing"),
    path("unsubscribe/<int:job_id>/", views.track_unsubscribe_full_view, name="unsubscribe"),
    path("logs/", views.logs_view, name="logs"),
    path("profile/", views.profile_view, name="profile"),
    path("change-password/", views.change_password, name="change_password"),
    path("api/clients/", views.api_clients, name="api_clients"),
    path("api/campaigns/", views.api_campaigns, name="api_campaigns"),
    path("reports/batch/<int:batch_id>/", views.batch_detail_view, name="batch_detail"),
    path("invoices/", views.invoices_view, name="invoices"),
    path("invoices/create/", views.create_invoice_view, name="create_invoice"),
    path("invoices/<uuid:invoice_id>/", views.invoice_detail_view, name="invoice_detail"),
    path("send/", views.send_email_wizard, name="send_email_wizard"),
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
    # Stripe invoice actions
    path(
        "invoices/<uuid:invoice_id>/stripe-send/",
        views.invoice_stripe_send,
        name="invoice_stripe_send",
    ),
    path("api/revenue/", views_revenue.RevenueIntelligenceAPI.as_view(), name="api_revenue"),
    path("api/revenue/view/", views_revenue.revenue_dashboard_view, name="revenue_dashboard"),
    # Billing API
    path("services/", views_billing.services_management_view, name="services_management"),
    path(
        "api/billing/services/",
        views_billing.ServiceCatalogAPI.as_view(),
        name="api_billing_services",
    ),
    path(
        "api/billing/services/<int:service_id>/",
        views_billing.ServiceCatalogAPI.as_view(),
        name="api_billing_services_detail",
    ),
    path(
        "api/billing/calculate/",
        views_billing.InvoiceCalculationAPI.as_view(),
        name="api_billing_calculate",
    ),
    path(
        "api/billing/create/", views_billing.CreateInvoiceAPI.as_view(), name="api_billing_create"
    ),
    path("client-setup/", views.client_setup_view, name="client_setup"),
    path("client-setup/create/", views.client_create_view, name="client_create"),
    path("client-setup/<int:charity_id>/", views.client_setup_view, name="client_setup_edit"),
    path("switch-client/clear/", views.clear_client_context, name="clear_client_context"),
    path("switch-client/<int:charity_id>/", views.switch_client, name="switch_client"),
    path(
        "client-setup/manage-password/<int:user_id>/",
        views.manage_user_password,
        name="manage_user_password",
    ),
    path("client-setup/remove-member/<int:member_id>/", views.remove_member, name="remove_member"),
    # Clients Management
    path("clients/", views_clients.clients_view, name="clients"),
    path("clients/<int:client_id>/edit/", views_clients.client_edit_view, name="client_edit"),
    path(
        "clients/<int:client_id>/campaign/",
        views_clients.client_campaign_redirect,
        name="client_campaign_redirect",
    ),
    # Campaigns
    path("campaigns/", views_campaign.admin_campaigns, name="admin_campaigns"),
    path("campaigns/create/", views_campaign.campaign_create, name="campaign_create"),
    path("campaigns/<uuid:campaign_id>/", views_campaign.campaign_detail, name="campaign_detail"),
    path("campaigns/<uuid:campaign_id>/edit/", views_campaign.campaign_edit, name="campaign_edit"),
    path(
        "campaigns/<uuid:campaign_id>/fields/",
        views_campaign.campaign_fields,
        name="campaign_fields",
    ),
    path(
        "campaigns/<uuid:campaign_id>/fields/add/",
        views_campaign.campaign_field_add,
        name="campaign_field_add",
    ),
    path(
        "campaigns/<uuid:campaign_id>/fields/<int:field_id>/delete/",
        views_campaign.campaign_field_delete,
        name="campaign_field_delete",
    ),
    # Webhooks
    path(
        "webhooks/stripe/",
        views_webhooks.StripeWebhookView.as_view(),
        name="stripe_webhook",
    ),
    path(
        "webhooks/cloudflare/",
        views_webhooks.CloudflareWebhookView.as_view(),
        name="cloudflare_webhook",
    ),
]
