from django.urls import path

from charity.api.views import BulkDonationIngestAPIView, DonationIngestAPIView

from . import views

urlpatterns = [
    path("upload-csv/", views.upload_csv_and_process, name="upload_csv"),
    path("api/donations/", DonationIngestAPIView.as_view(), name="ingest_donation"),
    path("api/donations/bulk/", BulkDonationIngestAPIView.as_view(), name="ingest_donations_bulk"),
]
