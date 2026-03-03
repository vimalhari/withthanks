from django.urls import path

from . import api_reports, views_analytics

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
        api_reports.CampaignReportAPIView.as_view(),
        name="api_campaign_report",
    ),
]
