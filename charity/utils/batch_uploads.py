from __future__ import annotations

import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from charity.models import Campaign, Charity, DonationBatch
from charity.tasks import batch_process_csv


def create_and_enqueue_csv_batch(
    *,
    charity: Charity,
    csv_file,
    campaign: Campaign | None = None,
) -> DonationBatch:
    """Create a CSV-backed DonationBatch and enqueue background processing."""
    if campaign and campaign.charity_id != charity.id:
        raise ValueError("Campaign must belong to the supplied charity.")

    donation_batch = DonationBatch.objects.create(
        charity=charity,
        campaign=campaign,
        campaign_name=campaign.name if campaign else "",
        batch_number=DonationBatch.get_next_batch_number(charity),
        csv_filename=csv_file.name,
    )

    file_name = f"uploads/csv/{uuid.uuid4()}_{csv_file.name}"
    saved_path = default_storage.save(file_name, ContentFile(csv_file.read()))
    donation_batch.csv_filename = saved_path
    donation_batch.save(update_fields=["csv_filename"])

    batch_process_csv.apply_async(args=(donation_batch.id,))
    return donation_batch
