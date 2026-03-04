from django.urls import path

from . import views_analytics
from .api import views_reports

urlpatterns = [
    path("", views_analytics.AnalyticsHomeView.as_view(), name="analytics_home"),
    path(
        "video-engagement/", views_analytics.VideoEngagementView.as_view(), name="analytics_video"
    ),
    path("delivery/", views_analytics.DeliveryDashboardView.as_view(), name="analytics_delivery"),
    path(
        "campaign-performance/",
        views_analytics.CampaignPerformanceView.as_view(),
        name="analytics_campaigns",
    ),
    path("unified/", views_analytics.UnifiedAnalyticsView.as_view(), name="analytics_unified"),
    # Export Endpoints
    path(
        "export/csv/",
        views_analytics.ExportAnalyticsView.as_view(),
        {"format": "csv"},
        name="analytics_export_csv",
    ),
    path(
        "export/excel/",
        views_analytics.ExportAnalyticsView.as_view(),
        {"format": "excel"},
        name="analytics_export_excel",
    ),
    # API Endpoints
    path(
        "api/charts/<str:chart_type>/",
        views_analytics.ChartDataAPIView.as_view(),
        name="analytics_api_charts",
    ),
    path(
        "api/unified-data/",
        views_analytics.UnifiedDashboardDataAPI.as_view(),
        name="analytics_api_unified_data",
    ),
    # Advanced Analytics Webhooks & Reports
    path(
        "api/reports/campaign/<uuid:campaign_id>/",
        views_reports.CampaignReportAPIView.as_view(),
        name="api_campaign_report",
    ),
    # --- Internal Reports (superuser only) ---
    path(
        "internal/revenue/",
        views_analytics.InternalRevenueReportView.as_view(),
        name="internal_revenue",
    ),
    path(
        "internal/volume/",
        views_analytics.InternalVolumeReportView.as_view(),
        name="internal_volume",
    ),
    path(
        "internal/adoption/",
        views_analytics.InternalAdoptionReportView.as_view(),
        name="internal_adoption",
    ),
    path(
        "internal/storage/",
        views_analytics.InternalStorageReportView.as_view(),
        name="internal_storage",
    ),
    # --- Client / External Reports (charity-scoped) ---
    path(
        "client/campaign-summary/",
        views_analytics.ClientCampaignSummaryView.as_view(),
        name="client_campaign_summary",
    ),
    path(
        "client/video-engagement/",
        views_analytics.ClientVideoEngagementView.as_view(),
        name="client_video_engagement",
    ),
    path(
        "client/donor-heatmap/",
        views_analytics.ClientDonorHeatmapView.as_view(),
        name="client_donor_heatmap",
    ),
    path(
        "client/list-hygiene/",
        views_analytics.ClientListHygieneView.as_view(),
        name="client_list_hygiene",
    ),
    path(
        "client/billing-snapshot/",
        views_analytics.ClientBillingSnapshotView.as_view(),
        name="client_billing_snapshot",
    ),
]
