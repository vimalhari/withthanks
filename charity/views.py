# charity/views.py
import csv
import logging
import traceback
from decimal import Decimal

from django.shortcuts import render
from django.utils.dateparse import parse_datetime

from charity.models import Campaign
from charity.services.video_dispatch import dispatch_donation_video

from .forms import CSVUploadForm

logger = logging.getLogger(__name__)


def upload_csv_and_process(request):
    """
    Handle CSV upload, generate personalized first 5s of video with TTS and overlay,
    append remaining base video, and send via email.
    """
    message = None
    visible_errors = []  # 👈 store short messages for display

    if request.method == "POST":
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES["csv_file"]

            try:
                lines = csv_file.read().decode("utf-8").splitlines()
            except Exception as e:
                message = "Uploaded file must be a UTF-8 encoded CSV."
                logger.exception("CSV decode failed: %s", e)
                return render(request, "upload_csv.html", {"form": form, "message": message})

            charity = form.cleaned_data["charity"]
            campaign_type = form.cleaned_data["campaign_type"]
            reader = csv.DictReader(lines)
            processed_count = 0
            errors = []

            for i, row in enumerate(reader, start=1):
                try:
                    name = (row.get("name") or "donor").strip()
                    amount_str = (row.get("amount") or "").strip()
                    email = (row.get("email") or "").strip()
                    donated_at_raw = (row.get("donated_at") or "").strip()

                    if not email:
                        logger.info("Row %d skipped: no email", i)
                        continue

                    if not amount_str:
                        raise ValueError("amount is required")

                    amount = Decimal(amount_str)
                    donated_at = parse_datetime(donated_at_raw) if donated_at_raw else None

                    dispatch_donation_video(
                        charity=charity,
                        donor_email=email,
                        donor_name=name,
                        amount=amount,
                        donated_at=donated_at,
                        source="CSV",
                        campaign_type=campaign_type,
                    )
                    processed_count += 1

                except Exception as exc:
                    logger.error("Row %d failed: %s\n%s", i, exc, traceback.format_exc())
                    errors.append({"row": i, "error": str(exc)})
                    # 👇 add short visible message for web display
                    visible_errors.append(f"Row {i}: {exc}")

            campaign_label = dict(Campaign.CampaignType.choices).get(campaign_type, campaign_type)
            message = f"Processed {processed_count} rows for {charity.name} ({campaign_label}) successfully!"
            if errors:
                message += f" ({len(errors)} rows failed.)"

    else:
        form = CSVUploadForm()

    # 👇 Pass visible_errors to the template
    return render(
        request, "upload_csv.html", {"form": form, "message": message, "errors": visible_errors}
    )
