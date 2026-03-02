from django.urls import path

from . import views

urlpatterns = [
    path("upload-csv/", views.upload_csv_and_process, name="upload_csv"),
]

