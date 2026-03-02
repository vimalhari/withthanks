# charity/api/urls.py
from django.urls import path

from .views import BulkDonationIngestAPIView, DonationIngestAPIView, TaskStatusAPIView

urlpatterns = [
    path("donations/ingest/", DonationIngestAPIView.as_view(), name="donation-ingest"),
    path(
        "donations/bulk-ingest/", BulkDonationIngestAPIView.as_view(), name="donation-bulk-ingest"
    ),
    path("tasks/<str:task_id>/", TaskStatusAPIView.as_view(), name="task-status"),
]
