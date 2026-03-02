# charity/api/urls.py
from django.urls import path

from .views import BulkDonationIngestAPIView, DonationIngestAPIView

urlpatterns = [
    path("donations/ingest/", DonationIngestAPIView.as_view(), name="donation-ingest"),
    path(
        "donations/bulk-ingest/", BulkDonationIngestAPIView.as_view(), name="donation-bulk-ingest"
    ),
]
