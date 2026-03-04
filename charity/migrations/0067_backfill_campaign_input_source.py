"""
Data migration: backfill Campaign.input_source.

For each Campaign, if any of its linked Donations were ingested via the API
(Donation.source == "API"), set input_source = "API".  All others keep the
default of "CSV".  VDM campaigns are always forced to "CSV" regardless.
"""

from __future__ import annotations

from django.db import migrations


def backfill_input_source(apps, schema_editor):
    Campaign = apps.get_model("charity", "Campaign")
    Donation = apps.get_model("charity", "Donation")

    # Build a set of charity IDs that have at least one API-sourced donation.
    # (Donation has no campaign FK — it links to Charity directly.)
    api_charity_ids = set(
        Donation.objects.filter(source="API")
        .values_list("charity_id", flat=True)
        .distinct()
    )

    for campaign in Campaign.objects.all():
        if campaign.campaign_type == "VDM":
            # VDM is always CSV — enforce regardless of donation records.
            if campaign.input_source != "CSV":
                campaign.input_source = "CSV"
                campaign.save(update_fields=["input_source"])
        elif campaign.client_id in api_charity_ids:
            # THANK_YOU campaign for a charity that uses the API pipeline.
            campaign.input_source = "API"
            campaign.save(update_fields=["input_source"])
        # else: already "CSV" by default — no update needed.


class Migration(migrations.Migration):

    dependencies = [
        ("charity", "0066_fix_index_name_and_help_texts"),
    ]

    operations = [
        migrations.RunPython(backfill_input_source, migrations.RunPython.noop),
    ]
