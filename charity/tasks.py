import contextlib
import csv
import logging
import os
import time
import traceback
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.urls import reverse
from django.utils.timezone import now

from .models import DonationBatch, DonationJob, EmailTracking, UnsubscribedUser
from .models_analytics import EmailEvent, VideoEvent
from .services.video_builder import VideoSpec, build_personalized_video
from .utils.cloudflare_stream import upload_video_to_stream
from .utils.resend_utils import send_video_email

logger = logging.getLogger(__name__)


def cleanup_intermediate(files, final_file):
    """Delete TTS and temporary files after final video is ready."""
    for f in files:
        if f and os.path.exists(f) and f != final_file:
            try:
                os.remove(f)
            except Exception as err:
                logger.warning(f"Failed to delete file {f}: {err}")


@shared_task(bind=True, max_retries=10, default_retry_delay=2, rate_limit="2/s")
def process_donation_row(self, job_id):
    """
    STRICT PROCESSING PIPELINE: VDM vs WithThanks
    """
    from django.template.loader import (
        render_to_string,  # Import here to avoid circular imports if any
    )

    start_time = time.time()
    intermediate_files = []

    try:
        # Fetch Job with related Client (Charity) and Campaign
        job = DonationJob.objects.select_related("charity", "campaign", "donation_batch").get(
            id=job_id
        )
        client = job.charity
        campaign = job.campaign

        # 1. CHECK UNSUBSCRIBE STATUS FIRST
        if UnsubscribedUser.is_unsubscribed(job.email, client):
            logger.info(
                f"Skipping Job {job.id}: User {job.email} is unsubscribed from {client.organization_name}"
            )
            job.status = "skipped"
            job.error_message = "User is unsubscribed"
            job.save(update_fields=["status", "error_message"])
            return {"status": "skipped", "reason": "unsubscribed"}

        job.status = "processing"
        job.save(update_fields=["status"])

        # DETERMINE MODE
        # Default to WithThanks if not specified, but usually it comes from Campaign
        mode = "WithThanks"
        if campaign and campaign.appeal_type:
            mode = campaign.appeal_type

        logger.info(f"Processing Job {job.id} in Mode: {mode}")

        # RESOLVE BASE VIDEO (Required for most flows)
        base_video_path = None
        if campaign:
            if mode == "VDM" and campaign.charity_video:
                base_video_path = campaign.charity_video.path
            elif mode == "WithThanks" and campaign.gratitude_video:
                base_video_path = campaign.gratitude_video.path
            elif campaign.video_template_override:
                base_video_path = campaign.video_template_override.path

        # Log Video Generation started (eventually update on success)
        VideoEvent.objects.create(job=job, campaign=campaign, event_type="GENERATED")

        if not base_video_path and client.default_template_video:
            base_video_path = client.default_template_video.path

        # LOGIC BRANCHING
        final_video_path = None
        is_card_only = False
        template_name = "withthanks.html"  # Default
        image_url = f"{settings.MEDIA_URL}email_templates/thankyou.png"  # Default image

        # Ensure MEDIA_URL is absolute or handled correctly by the client
        # For email templates, we often need a full URL if images are hosted,
        # or just the path if the email client resolves it (unlikely without full URL).
        # Assuming there's a SERVER_BASE_URL to prepend.
        server_url = getattr(settings, "SERVER_BASE_URL", "https://hirefella.com").rstrip("/")
        full_image_url = f"{server_url}{image_url}"

        if mode == "VDM":
            # MODE 1: VDM (Video Direct Marketing)
            # - No personalization
            # - No voice generation
            # - Upload charity_video to Cloudflare Stream ONCE per campaign (cached)
            # - All 10k recipients share the same CF-hosted URL — zero server egress
            # - Use vdm.html

            if not base_video_path or not os.path.exists(base_video_path):
                raise FileNotFoundError(f"Base video template missing for VDM Job {job.id}")

            final_video_path = base_video_path
            template_name = "vdm.html"
            image_url = f"{settings.MEDIA_URL}email_templates/vdm_banner.png"
            full_image_url = f"{server_url}{image_url}"

            unsubscribe_path = reverse("unsubscribe", kwargs={"job_id": job.id})
            unsubscribe_url = f"{server_url}{unsubscribe_path}"

            # --- Cloudflare Stream: upload once, cache on Campaign ---
            cf_stream_enabled = getattr(settings, "CLOUDFLARE_STREAM_ENABLED", False)
            if cf_stream_enabled and campaign:
                if campaign.cf_stream_video_url:
                    # Already uploaded — reuse cached CDN URL
                    logger.info(
                        f"Job {job.id}: Reusing cached CF Stream URL for campaign {campaign.id}"
                    )
                else:
                    # First job for this campaign — upload to Cloudflare Stream
                    try:
                        logger.info(
                            f"Job {job.id}: Uploading VDM video to Cloudflare Stream "
                            f"for campaign {campaign.id}"
                        )
                        cf_result = upload_video_to_stream(
                            base_video_path,
                            meta_name=f"{campaign.name} — VDM",
                        )
                        campaign.cf_stream_video_id = cf_result.video_id
                        campaign.cf_stream_video_url = cf_result.playback_url
                        campaign.save(
                            update_fields=["cf_stream_video_id", "cf_stream_video_url"]
                        )
                        logger.info(
                            f"Job {job.id}: CF Stream upload success — "
                            f"uid={cf_result.video_id}"
                        )
                    except Exception as cf_err:
                        # Non-fatal: fall back to local URL
                        logger.warning(
                            f"Job {job.id}: CF Stream upload failed, falling back to "
                            f"local URL. Error: {cf_err}"
                        )

        elif mode == "Gratitude":
            # MODE 3: Gratitude (New Template)
            if not base_video_path and client.default_template_video:
                base_video_path = client.default_template_video.path

            if not base_video_path or not os.path.exists(base_video_path):
                # Fallback to campaign video if available
                if campaign and campaign.gratitude_video:
                    base_video_path = campaign.gratitude_video.path
                elif campaign and campaign.charity_video:
                    base_video_path = campaign.charity_video.path

            final_video_path = base_video_path

            # Use the new template
            template_name = "emails/donation_thank_you.html"

            # Use Gratitude Banner if available on Campaign, else Default
            image_url = f"{settings.MEDIA_URL}email_templates/thankyou.png"
            if campaign and campaign.image_banner:
                with contextlib.suppress(Exception):
                    image_url = campaign.image_banner.url

            full_image_url = f"{server_url}{image_url}"

        elif mode == "WithThanks":
            # MODE 2: WithThanks
            # Check 30-day deduplication FIRST

            thirty_days_ago = now() - timedelta(days=30)

            # Check if this email received a SUCCESSFUL video in last 30 days
            has_recent_video = DonationJob.objects.filter(
                charity=client, email=job.email, status="success", completed_at__gte=thirty_days_ago
            ).exists()

            if has_recent_video or (job.media_type_override == "image"):
                # DEDUPLICATED -> Send Card Only
                logger.info(
                    f"Job {job.id}: 30-day deduplication or override triggering Card-Only mode."
                )
                is_card_only = True

                # Use Gratitude Asset if available (Prioritize Campaign)
                if campaign and campaign.gratitude_video:
                    final_video_path = campaign.gratitude_video.path
                    logger.info(f"Job {job.id}: Using campaign gratitude asset: {final_video_path}")
                elif client.gratitude_card:
                    final_video_path = client.gratitude_card.path
                    logger.info(
                        f"Job {job.id}: Using specific client gratitude card: {final_video_path}"
                    )
                else:
                    final_video_path = (
                        None  # Fallback to default image in template if no card uploaded
                    )

                template_name = "withthanks_card_only.html"
                image_url = f"{settings.MEDIA_URL}email_templates/thankyou.png"
                full_image_url = f"{server_url}{image_url}"

            else:
                # Check Personalization
                is_personalized = False
                template_name = "withthanks.html"
                image_url = f"{settings.MEDIA_URL}email_templates/thankyou.png"  # Same image for both personalized/default logic
                full_image_url = f"{server_url}{image_url}"

                if campaign:
                    is_personalized = campaign.is_personalized

                if is_personalized:
                    # PERSONALIZED FLOW — delegate to shared video builder
                    raw_script = ""
                    if campaign and campaign.voiceover_script_override:
                        raw_script = campaign.voiceover_script_override
                    elif client.default_voiceover_script:
                        raw_script = client.default_voiceover_script

                    if not base_video_path or not os.path.exists(base_video_path):
                        raise FileNotFoundError(
                            f"Base video template missing for stitching Job {job.id}"
                        )

                    spec = VideoSpec(
                        donor_name=str(job.donor_name),
                        donation_amount=str(job.donation_amount),
                        charity_name=client.organization_name,
                        campaign_name=campaign.name if campaign else "",
                        voiceover_script=raw_script or None,
                        voice_id=client.default_voice_id or "",
                        base_video_path=base_video_path,
                        overlay_text="",
                    )
                    final_video_path, tts_path = build_personalized_video(spec)
                    intermediate_files.append(tts_path)

                else:
                    # NOT PERSONALIZED -> Send Default Video
                    if not base_video_path or not os.path.exists(base_video_path):
                        logger.warning(
                            f"Base video template missing for Default Video Job {job.id}. Falling back to Card Only."
                        )
                        is_card_only = True
                        # Use Gratitude Asset if available
                        if client.gratitude_card:
                            final_video_path = client.gratitude_card.path
                        else:
                            final_video_path = None
                        template_name = "withthanks_card_only.html"
                    else:
                        final_video_path = base_video_path

        # TRACKING: Create EmailTracking record
        EmailTracking.objects.get_or_create(
            job=job,
            defaults={
                "campaign": campaign,
                "batch": job.donation_batch,
                "user_id": job.id,
                "appeal_type": mode,
                "sent": True,  # Assume sent if we get to this point (will be saved shortly)
                "vdm": False,
            },
        )

        # Log SENT event for analytics
        EmailEvent.objects.create(campaign=campaign, job=job, event_type="SENT")

        # TRACKING: Generate URLs
        # Base Params: c=campaign_id, b=batch_id, u=job_id, type=appeal_type
        # We use job.id (u) as the primary key for lookup in views as it's unique enough and linked to everything.

        # 1. Tracking Pixel URL
        # Path: /track/open/?c=...&b=...&u=...&type=...
        track_open_path = reverse("track_open")
        pixel_url = f"{server_url}{track_open_path}?u={job.id}&type={mode}"
        if campaign:
            pixel_url += f"&c={campaign.id}"
        if job.donation_batch:
            pixel_url += f"&b={job.donation_batch.id}"

        # 2. Click/Redirect URL (Wraps the video/image link)
        # Path: /track/click/?u=...&type=...
        track_click_path = reverse("track_click")
        click_url = f"{server_url}{track_click_path}?u={job.id}&type={mode}"
        if campaign:
            click_url += f"&c={campaign.id}"
        if job.donation_batch:
            click_url += f"&b={job.donation_batch.id}"

        # 3. Unsubscribe URL
        # Path: /track/unsubscribe/?u=...&type=...
        # STRICT LOGIC: Omit for THANKYOU campaigns
        unsubscribe_url = None
        if campaign and campaign.appeal_type != "THANKYOU":
            track_unsub_path = reverse("track_unsubscribe_full")
            unsubscribe_url = f"{server_url}{track_unsub_path}?u={job.id}&type={mode}"

        # 4. Resolve Public Video Link for Template
        # For VDM: prefer Cloudflare Stream URL (CDN) over local server path
        video_url_link = ""
        cf_stream_url = None
        if mode == "VDM" and campaign and campaign.cf_stream_video_url:
            video_url_link = campaign.cf_stream_video_url
            cf_stream_url = campaign.cf_stream_video_url
            logger.info(f"Job {job.id}: Using CF Stream URL: {video_url_link}")
        elif final_video_path:
            try:
                rel_path = os.path.relpath(final_video_path, settings.MEDIA_ROOT)
                clean_rel_path = rel_path.replace("\\", "/")
                # Ensure we don't have double slashes in the path part, but preserve protocol
                m_url = settings.MEDIA_URL
                if not m_url.startswith("/"):
                    m_url = "/" + m_url

                # Combine correctly: server_url (no trailing slash) + m_url (leading slash) + clean_rel_path
                video_url_link = (
                    f"{server_url}{m_url}{clean_rel_path}".replace("//", "/")
                    .replace("http:/", "http://")
                    .replace("https:/", "https://")
                )
            except ValueError:
                video_url_link = f"{server_url}/media/outputs/{os.path.basename(final_video_path)}"

        context = {
            "donor_name": job.donor_name,
            "donation_amount": job.donation_amount,
            "organization_name": client.organization_name,
            "from_email": client.contact_email,
            "image_url": full_image_url,
            "video_url": video_url_link,  # CF Stream URL for VDM, local URL otherwise
            "cf_stream_url": cf_stream_url,  # Non-None only for VDM with CF enabled
            "is_video_card": is_card_only,
            "campaign_name": campaign.name if campaign else "WithThanks Campaign",
            "unsubscribe_url": unsubscribe_url,  # Now available for both modes if needed
            # New Tracking Context
            "tracking_pixel_url": pixel_url,
            "tracking_click_url": click_url,
        }

        # Load template from charity/email_templates/
        # Django template loader searches using dirs configured in settings.
        # Assuming 'charity/email_templates/' leads to correct file relative to template dirs.
        # We moved files to charity/templates/charity/email_templates/
        # So we should reference them as charity/email_templates/vdm.html etc.
        full_template_path = f"charity/email_templates/{template_name}"
        email_html = render_to_string(full_template_path, context)

        # SEND EMAIL (Resend)
        # Determine Subject
        subject = "Personalized thank-you message"
        if job.donation_batch and job.donation_batch.campaign_name:
            subject = job.donation_batch.campaign_name
        elif campaign:
            subject = campaign.name

        try:
            send_video_email(
                to_email=job.email,
                file_path=final_video_path,
                job_id=str(job.id),
                donor_name=job.donor_name,
                donation_amount=job.donation_amount,
                from_email=client.contact_email,
                organization_name=client.organization_name,
                subject=subject,
                is_card_only=is_card_only,
                html=email_html,  # Pass rendered HTML
            )
        except Exception as e:
            job.status = "failed"
            job.error_message = f"Resend failed: {e!s}"
            job.save()
            # Log failed event
            EmailEvent.objects.create(job=job, campaign=campaign, event_type="FAILED")
            logger.error(f"Job {job_id} Resend failure: {e}")
            cleanup_intermediate(intermediate_files, final_video_path)
            # Re-raising allows Celery retry
            raise e

        # SUCCESS
        generation_time = round(time.time() - start_time, 2)
        job.status = "success"
        job.video_path = final_video_path if final_video_path else ""
        job.appeal_type = mode  # Save mode to job

        job.generation_time = generation_time
        job.completed_at = now()
        job.save()

        # Cleanup
        if final_video_path and final_video_path != base_video_path:
            # Only delete if we generated a NEW file (Stitched).
            # If we used base_video_path directly (VDM/Default), DO NOT DELETE IT!
            cleanup_intermediate(intermediate_files, final_video_path)
        else:
            cleanup_intermediate(intermediate_files, None)

        logger.info(f"✅ Job {job.id} success in {generation_time}s")

        # Sync into normalized Donor/Donation/VideoSendLog tables
        from .services.sync_bridge import sync_job_to_normalized_models

        sync_job_to_normalized_models(job)

    except Exception as exc:
        logger.error(f"❌ Job {job_id} critical failure: {exc}\n{traceback.format_exc()}")
        try:
            job = DonationJob.objects.get(id=job_id)
            job.status = "failed"
            job.error_message = str(exc)
            job.save()
        except Exception as save_err:
            logger.error(f"Could not mark job {job_id} as failed: {save_err}")

        cleanup_intermediate(intermediate_files, None)
        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Async wrapper for the Stage-3 API video dispatch pipeline
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def dispatch_donation_video_task(
    self,
    *,
    charity_id: int,
    donor_email: str,
    donor_name: str,
    amount: str,
    donated_at: str | None = None,
    source: str = "API",
    campaign_type: str = "THANK_YOU",
) -> dict:
    """
    Celery wrapper around :func:`charity.services.video_dispatch.dispatch_donation_video`.

    All arguments are JSON-serialisable so the task can be sent via any
    Celery broker.  The heavy work (TTS, FFmpeg stitching, email send) runs
    in the worker, keeping the API request/response cycle fast.
    """
    from decimal import Decimal

    from django.utils.dateparse import parse_datetime

    from charity.models import Charity
    from charity.services.video_dispatch import dispatch_donation_video

    try:
        charity = Charity.objects.get(id=charity_id)
        parsed_at = parse_datetime(donated_at) if donated_at else None

        result = dispatch_donation_video(
            charity=charity,
            donor_email=donor_email,
            donor_name=donor_name,
            amount=Decimal(amount),
            donated_at=parsed_at,
            source=source,
            campaign_type=campaign_type,
        )

        return {
            "donation_id": result.donation_id,
            "send_log_id": result.send_log_id,
            "donor_email": result.donor_email,
            "send_kind": result.send_kind,
            "campaign_type": result.campaign_type,
            "video_path": result.video_path,
            "stream_video_id": result.stream_video_id,
            "stream_playback_url": result.stream_playback_url,
        }
    except Exception as exc:
        logger.error("dispatch_donation_video_task failed for %s: %s", donor_email, exc)
        raise self.retry(exc=exc) from exc


@shared_task
def batch_process_csv(batch_id):
    """
    Scalable CSV processor: reads file and triggers individual jobs.
    """
    try:
        batch = DonationBatch.objects.select_related("charity", "campaign").get(id=batch_id)
        client = batch.charity
        campaign = batch.campaign

        # Resolve CSV path (Assuming it was saved to media)
        # Using a safer approach with the file on disk
        from django.core.files.storage import default_storage

        file_path = (
            default_storage.path(batch.csv_filename)
            if not os.path.isabs(batch.csv_filename)
            else batch.csv_filename
        )

        if not os.path.exists(file_path):
            logger.error(f"Batch {batch_id}: CSV file not found at {file_path}")
            return

        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            # Normalize headers
            if reader.fieldnames:
                reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

            count = 0
            for _, row in enumerate(reader, start=1):
                # Flexible mapping
                name = row.get("donor_name") or row.get("name") or row.get("full name") or "Donor"
                email = (
                    row.get("email")
                    or row.get("recipient email")
                    or row.get("email-id")
                    or row.get("email address")
                )
                amount = (
                    row.get("donation_amount") or row.get("amount") or row.get("donation") or "0"
                )

                if not email:
                    continue

                # Create Job
                job = DonationJob.objects.create(
                    donor_name=name,
                    donation_amount=amount,
                    email=email.strip(),
                    status="pending",
                    charity=client,
                    campaign=campaign,
                    donation_batch=batch,
                )

                # Trigger specific job task
                process_donation_row.apply_async(args=(job.id,))
                count += 1

        logger.info(f"Successfully queued {count} jobs from batch {batch_id}")

    except Exception as e:
        logger.error(f"Error in batch_process_csv {batch_id}: {e}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Periodic tasks (called by Celery Beat — see withthanks/celery.py)
# ---------------------------------------------------------------------------


@shared_task
def refresh_all_campaign_stats():
    """Refresh materialized CampaignStats for all campaigns."""
    from .models import Campaign
    from .models_analytics import CampaignStats

    campaigns = Campaign.objects.all()
    refreshed = 0
    for campaign in campaigns:
        stats, _ = CampaignStats.objects.get_or_create(campaign=campaign)
        stats.update_stats()
        refreshed += 1
    logger.info(f"Refreshed CampaignStats for {refreshed} campaigns")
    return {"refreshed": refreshed}


@shared_task
def mark_overdue_invoices():
    """Transition Sent invoices past their due date to Overdue status."""
    from .models import Invoice

    overdue = Invoice.objects.filter(
        status="Sent",
        due_date__lt=now().date(),
    ).update(status="Overdue")
    logger.info(f"Marked {overdue} invoices as Overdue")
    return {"marked_overdue": overdue}


@shared_task
def cleanup_stale_jobs():
    """Reset jobs stuck in 'processing' for over 2 hours back to 'failed'."""
    cutoff = now() - timedelta(hours=2)
    stale = DonationJob.objects.filter(
        status="processing",
        updated_at__lt=cutoff,
    ).update(status="failed", error_message="Stale job — timed out after 2 hours")
    logger.info(f"Cleaned up {stale} stale processing jobs")
    return {"stale_cleaned": stale}


@shared_task
def prune_voiceover_cache():
    """Delete voiceover cache files older than 30 days."""
    cache_dir = os.path.join(settings.MEDIA_ROOT, "voiceover_cache")
    if not os.path.isdir(cache_dir):
        return {"pruned": 0}

    cutoff = time.time() - (30 * 86400)  # 30 days in seconds
    pruned = 0
    for fname in os.listdir(cache_dir):
        fpath = os.path.join(cache_dir, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                pruned += 1
        except Exception as err:
            logger.warning(f"Failed to prune {fpath}: {err}")
    logger.info(f"Pruned {pruned} old voiceover cache files")
    return {"pruned": pruned}


@shared_task
def cleanup_old_videos():
    """Delete generated video files from VIDEO_OUTPUT_DIR older than 7 days."""
    video_dir = str(settings.VIDEO_OUTPUT_DIR)
    if not os.path.isdir(video_dir):
        return {"deleted": 0}

    cutoff = time.time() - (7 * 86400)  # 7 days in seconds
    deleted = 0
    for fname in os.listdir(video_dir):
        fpath = os.path.join(video_dir, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except Exception as err:
            logger.warning(f"Failed to delete {fpath}: {err}")
    logger.info(f"Deleted {deleted} old video files from output dir")
    return {"deleted": deleted}

