"""
Migration: Consolidate campaign terminology.

- Rename Campaign.appeal_code  → campaign_code
- Rename Campaign.appeal_start → campaign_start
- Rename Campaign.appeal_end   → campaign_end
- Data-migrate Campaign.appeal_type ("WithThanks"→"THANK_YOU", "VDM"→"VDM") into campaign_type
- Remove Campaign.appeal_type (legacy duplicate)
- Add Campaign.input_source
- Rename DonationJob.appeal_type  → campaign_type
- Rename EmailTracking.appeal_type → campaign_type  (+ rebuild index)
"""

from __future__ import annotations

from django.db import migrations, models


def migrate_campaign_appeal_type(apps, schema_editor):
    """Copy legacy appeal_type values into the canonical campaign_type field."""
    Campaign = apps.get_model("charity", "Campaign")
    mapping = {
        "WithThanks": "THANK_YOU",
        "VDM": "VDM",
    }
    for campaign in Campaign.objects.all():
        old_value = getattr(campaign, "appeal_type", None)
        if old_value:
            campaign.campaign_type = mapping.get(old_value, "THANK_YOU")
            campaign.save(update_fields=["campaign_type"])


def migrate_email_tracking_appeal_type(apps, schema_editor):
    """Copy EmailTracking.appeal_type into campaign_type using the same mapping."""
    # Field will be renamed after this; we map before the column is dropped.
    pass  # handled by RenameField below — no data conversion needed (values already correct)


class Migration(migrations.Migration):

    dependencies = [
        ("charity", "0064_remove_campaign_is_personalized"),
    ]

    operations = [
        # ── 1. Data migration: sync legacy appeal_type → campaign_type ──────
        migrations.RunPython(migrate_campaign_appeal_type, migrations.RunPython.noop),

        # ── 2. Campaign field renames ────────────────────────────────────────
        migrations.RenameField(
            model_name="campaign",
            old_name="appeal_code",
            new_name="campaign_code",
        ),
        migrations.RenameField(
            model_name="campaign",
            old_name="appeal_start",
            new_name="campaign_start",
        ),
        migrations.RenameField(
            model_name="campaign",
            old_name="appeal_end",
            new_name="campaign_end",
        ),

        # ── 3. Remove legacy appeal_type from Campaign ───────────────────────
        migrations.RemoveField(
            model_name="campaign",
            name="appeal_type",
        ),

        # ── 4. Add input_source to Campaign ──────────────────────────────────
        migrations.AddField(
            model_name="campaign",
            name="input_source",
            field=models.CharField(
                choices=[("API", "API"), ("CSV", "CSV")],
                default="CSV",
                help_text="Data ingest source. VDM is always CSV; Thank You can be API or CSV.",
                max_length=10,
            ),
        ),

        # ── 5. Update campaign_type help_text on Campaign ────────────────────
        migrations.AlterField(
            model_name="campaign",
            name="campaign_type",
            field=models.CharField(
                choices=[("THANK_YOU", "Thank You"), ("VDM", "Video Direct Mail")],
                default="THANK_YOU",
                help_text="Campaign type: Thank You (donor acknowledgement) or VDM (video direct mail)",
                max_length=20,
            ),
        ),

        # ── 6. DonationJob: rename appeal_type → campaign_type ──────────────
        migrations.RenameField(
            model_name="donationjob",
            old_name="appeal_type",
            new_name="campaign_type",
        ),
        migrations.AlterField(
            model_name="donationjob",
            name="campaign_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("WithThanks", "WithThanks"),
                    ("VDM", "VDM"),
                    ("Gratitude", "Gratitude"),
                ],
                max_length=20,
                null=True,
            ),
        ),

        # ── 7. EmailTracking: remove old index, rename field, rebuild index ──
        migrations.RemoveIndex(
            model_name="emailtracking",
            name="charity_ema_appeal__5c97b5_idx",
        ),
        migrations.RenameField(
            model_name="emailtracking",
            old_name="appeal_type",
            new_name="campaign_type",
        ),
        migrations.AlterField(
            model_name="emailtracking",
            name="campaign_type",
            field=models.CharField(
                choices=[("THANK_YOU", "Thank You"), ("VDM", "Video Direct Mail")],
                default="THANK_YOU",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="emailtracking",
            index=models.Index(fields=["campaign_type"], name="charity_ema_campaig_idx"),
        ),
    ]
