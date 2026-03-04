"""
Bridge between the CSV batch pipeline (DonationJob) and the API pipeline's
normalized models (Donor → Donation → VideoSendLog).

Called at the end of a successful ``process_donation_row`` to keep both model
hierarchies in sync so analytics, reporting, and the donor timeline reflect
*all* send activity — regardless of the ingestion channel.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.utils.timezone import now

logger = logging.getLogger(__name__)


def sync_job_to_normalized_models(job) -> dict | None:
    """
    Create or update Donor, Donation and VideoSendLog records from a
    completed :class:`DonationJob`.

    Returns a dict with the created record IDs, or *None* if the job cannot
    be synced (e.g. missing required data).

    This is intentionally **best-effort** — a failure here must never break
    the CSV pipeline.
    """
    # Lazy imports to avoid circular dependencies at module level.
    from charity.models import Campaign, Donation, Donor, VideoSendLog

    try:
        charity = job.charity
        if not charity:
            return None

        email = (job.email or "").strip().lower()
        if not email:
            return None

        donor_name = str(job.donor_name or "").strip() or email

        # ── Donor ──────────────────────────────────────────────────────
        donor, _ = Donor.objects.get_or_create(
            charity=charity,
            email=email,
            defaults={"full_name": donor_name},
        )
        if donor_name and donor.full_name != donor_name:
            donor.full_name = donor_name
            donor.save(update_fields=["full_name"])

        # ── Donation ───────────────────────────────────────────────────
        try:
            amount = Decimal(str(job.donation_amount or "0"))
        except (InvalidOperation, TypeError, ValueError):
            amount = Decimal("0")

        campaign_type = Campaign.CampaignType.THANK_YOU
        raw_mode = getattr(job, "campaign_type", None) or ""
        if raw_mode.upper() == "VDM":
            campaign_type = Campaign.CampaignType.VDM

        donated_at = getattr(job, "completed_at", None) or now()

        donation = Donation.objects.create(
            donor=donor,
            charity=charity,
            amount=amount,
            donated_at=donated_at,
            campaign_type=campaign_type,
            source="CSV",
        )

        # ── VideoSendLog ───────────────────────────────────────────────
        # Map CSV campaign_type → SendKind
        if raw_mode.lower() == "gratitude":
            send_kind = VideoSendLog.SendKind.GRATITUDE
        elif getattr(job, "media_type_override", None) == "image":
            send_kind = VideoSendLog.SendKind.TEMPLATE
        else:
            send_kind = VideoSendLog.SendKind.PERSONALIZED

        status = VideoSendLog.Status.SENT if job.status == "success" else VideoSendLog.Status.FAILED

        campaign = job.campaign  # may be None

        log = VideoSendLog.objects.create(
            charity=charity,
            donor=donor,
            donation=donation,
            campaign=campaign,
            campaign_type=campaign_type,
            send_kind=send_kind,
            status=status,
            recipient_email=email,
            video_file=getattr(job, "video_path", "") or "",
            error_message=getattr(job, "error_message", "") or "",
        )

        logger.debug(
            "Synced DonationJob %s → Donor %s / Donation %s / VSL %s",
            job.id,
            donor.id,
            donation.id,
            log.id,
        )

        return {
            "donor_id": donor.id,
            "donation_id": donation.id,
            "video_send_log_id": log.id,
        }

    except Exception:
        logger.exception("Failed to sync DonationJob %s to normalized models", job.id)
        return None
