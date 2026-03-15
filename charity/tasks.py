import contextlib
import csv
import io
import logging
import os
import time
import traceback
from datetime import timedelta
from email.utils import formataddr, parseaddr

from celery import chain, chord, group, shared_task
from django.conf import settings
from django.db.models import Count
from django.utils.timezone import now

from .analytics_models import EmailEvent, VideoEvent
from .exceptions import FatalTaskError
from .models import DonationBatch, DonationJob, EmailTracking, UnsubscribedUser
from .services.video_build_service import VideoSpec, build_personalized_video, render_script
from .services.video_pipeline_service import (
    StreamDelivery,
    build_tracking_urls,
    get_or_upload_campaign_stream,
    resolve_public_video_url,
    resolve_static_asset_url,
    resolve_storage_video_url,
    stream_safe_upload,
)
from .utils.csv_rows import (
    build_csv_recipient_name,
    build_email_greeting_line,
    build_vdm_recipient_name,
    extract_csv_recipient_parts,
    get_csv_row_value,
)
from .utils.resend_utils import send_video_email
from .utils.tracking_security import build_tracking_token

logger = logging.getLogger(__name__)

DEFAULT_VDM_EMAIL_BODY = (
    "We are excited to share some amazing updates with you! At {{ charity_name }}, "
    "we are constantly working to make a bigger impact, and we want you to be a part of it.\n\n"
    "Check out our latest campaign video to see what we've been up to.\n\n"
    "Your support makes everything possible. Let's make a difference together!"
)

DEFAULT_THANK_YOU_EMAIL_BODY = (
    "On behalf of {{ charity_name }}, thank you for your generous donation of {{ donation_amount }}.\n\n"
    "Your support helps sustain our work, and we have prepared a personal video message to express our appreciation."
)

DEFAULT_CARD_ONLY_EMAIL_BODY = (
    "On behalf of {{ charity_name }}, thank you for your generous donation of {{ donation_amount }}.\n\n"
    "We wanted to acknowledge your latest support with a separate digital thank-you card as a small token of our appreciation."
)


def _resolve_campaign_email_image(*, campaign, mode: str, fallback_image: str) -> str:
    """Return the storage path to the campaign email thumbnail or the mode fallback."""
    if campaign and campaign.email_thumbnail:
        return campaign.email_thumbnail.name
    return fallback_image


def _resolve_email_thumbnail_url(
    *,
    mode: str,
    image_path: str | None,
    server_url: str,
    stream_delivery: StreamDelivery,
) -> str | None:
    """Resolve the donor-facing thumbnail URL for an outbound campaign email."""
    full_image_url = resolve_storage_video_url(storage_path=image_path, server_url=server_url)
    if full_image_url:
        return full_image_url

    if mode == "VDM":
        if stream_delivery.is_cached and stream_delivery.thumbnail_url:
            return stream_delivery.thumbnail_url

        placeholder_url = resolve_static_asset_url(
            static_path="charity/img/video_placeholder.png",
            server_url=server_url,
        )
        return placeholder_url or None

    return stream_delivery.thumbnail_url or None


def cleanup_intermediate(files, final_file):
    """Delete TTS and temporary files after final video is ready."""
    for f in files:
        if f and os.path.exists(f) and f != final_file:
            try:
                os.remove(f)
            except Exception as err:
                logger.warning(f"Failed to delete file {f}: {err}")


def build_email_paragraphs(*, campaign, job, charity_name: str, default_body: str) -> list[str]:
    """Render the campaign email_body into paragraph-sized chunks, falling back to default_body."""
    raw_body = campaign.email_body if campaign and campaign.email_body else default_body
    rendered_body = render_script(
        raw_body,
        build_campaign_email_context(campaign=campaign, job=job, charity_name=charity_name),
    )
    return [paragraph.strip() for paragraph in rendered_body.split("\n\n") if paragraph.strip()]


def build_campaign_email_context(*, campaign, job, charity_name: str) -> dict[str, object]:
    """Return placeholder values used by campaign-configurable email content."""
    return {
        "donor_name": job.display_donor_name,
        "charity_name": charity_name,
        "campaign_name": campaign.name if campaign else "WithThanks Campaign",
        "donation_amount": job.donation_amount,
    }


def resolve_job_charity(job):
    """Return the charity associated with a staged donation job.

    Older jobs may be missing a direct charity FK even though the campaign or batch
    still points at the owning charity.
    """
    if job.charity_id:
        return job.charity
    if job.campaign_id and getattr(job.campaign, "charity_id", None):
        return job.campaign.charity
    if job.donation_batch_id and getattr(job.donation_batch, "charity_id", None):
        return job.donation_batch.charity
    return None


def resolve_sender_email(*, campaign, charity_name: str | None = None) -> str | None:
    """Return the donor-facing sender header for outbound campaign email delivery."""
    sender = (
        campaign.from_email
        if campaign and campaign.from_email
        else getattr(settings, "DEFAULT_FROM_EMAIL", None)
    )
    if not sender:
        return None

    _, sender_address = parseaddr(sender)
    if not sender_address:
        return sender

    display_name = (charity_name or "").strip()
    if not display_name:
        return sender_address

    return formataddr((display_name, sender_address))


def resolve_email_subject(*, campaign, job, charity_name: str) -> str:
    """Return the donor-facing subject line for outbound campaign email delivery."""
    if campaign and campaign.email_subject:
        return render_script(
            campaign.email_subject,
            build_campaign_email_context(campaign=campaign, job=job, charity_name=charity_name),
        )
    if campaign:
        return campaign.name
    return "Personalized thank-you message"


# ---------------------------------------------------------------------------
# Stage 1 — Validate & Prepare
# ---------------------------------------------------------------------------


@shared_task(bind=True, queue="default")
def validate_and_prep_job(self, job_id):
    """
    Stage 1 of 3.  Lightweight setup running on the *default* queue.

    Resolves processing mode, base video path, and the 30-day dedup flag.
    Sets job status to "processing" and returns all resolved state as a plain
    JSON-serialisable dict for Stage 2 to consume.
    """
    job = DonationJob.objects.select_related(
        "charity",
        "campaign",
        "campaign__charity",
        "donation_batch",
        "donation_batch__charity",
    ).get(id=job_id)
    client = resolve_job_charity(job)
    campaign = job.campaign

    job.status = "processing"
    job.save(update_fields=["status"])

    # Determine processing mode (default: WithThanks)
    mode = "WithThanks"
    if campaign and campaign.is_vdm:
        mode = "VDM"

    logger.info("Prep Job %s — mode: %s", job_id, mode)

    # Resolve base video R2 storage key (use .name not .path — no local filesystem).
    base_video_path = None
    if campaign:
        if mode == "VDM" and campaign.vdm_video:
            base_video_path = campaign.vdm_video.name
        elif campaign.base_video:
            base_video_path = campaign.base_video.name

    # Per-mode template / image defaults
    is_card_only = False
    template_name = "withthanks.html"
    server_url = getattr(settings, "SERVER_BASE_URL", "https://hirefella.com").rstrip("/")
    image_url = "email_templates/thankyou.png"

    if mode == "VDM":
        template_name = "vdm.html"
        image_url = _resolve_campaign_email_image(
            campaign=campaign,
            mode=mode,
            fallback_image="email_templates/vdm_banner.png",
        )

    elif mode == "WithThanks":
        image_url = _resolve_campaign_email_image(
            campaign=campaign,
            mode=mode,
            fallback_image=image_url,
        )
        # 30-day dedup check — uses the compound index added in migration 0059
        thirty_days_ago = now() - timedelta(days=30)
        has_recent_video = DonationJob.objects.filter(
            charity=client,
            email=job.email,
            status="success",
            completed_at__gte=thirty_days_ago,
        ).exists()
        if has_recent_video or (job.media_type_override == "image"):
            logger.info("Job %s: 30-day dedup / override → card-only mode.", job_id)
            is_card_only = True
            template_name = "withthanks_card_only.html"

    return {
        "job_id": job_id,
        "mode": mode,
        "base_video_path": base_video_path,
        "is_card_only": is_card_only,
        "template_name": template_name,
        "image_url": image_url,
        "server_url": server_url,
    }


# ---------------------------------------------------------------------------
# Stage 2 — Generate Video
# ---------------------------------------------------------------------------


@shared_task(bind=True, queue="video")
def generate_video_for_job(self, context):
    """
    Stage 2 of 3.  CPU / IO-heavy step running on the *video* queue.

    Runs TTS + FFmpeg stitching *only* when the mode actually requires a
    personalised video. For VDM and card-only / default WithThanks modes,
    an existing base video is referenced directly.

    For personalised jobs the finished video is uploaded to R2 and
    ``job.video_path`` is persisted to the DB *before* returning so that if
    Stage 3 fails and retries, it picks up the already-generated URL rather
    than re-running FFmpeg.

    A ``VideoEvent(GENERATED)`` is created only after a successful generation
    to avoid phantom events.
    """
    job_id = context["job_id"]
    mode = context["mode"]
    base_video_path = context["base_video_path"]
    is_card_only = context["is_card_only"]
    template_name = context["template_name"]

    job = DonationJob.objects.select_related(
        "charity",
        "campaign",
        "campaign__charity",
        "donation_batch",
        "donation_batch__charity",
    ).get(id=job_id)
    client = resolve_job_charity(job)
    campaign = job.campaign

    final_video_path = None
    intermediate_files = []

    from .utils.video_utils import download_base_video_to_tmp, upload_output_to_r2

    try:
        if mode == "VDM":
            if not base_video_path:
                raise FatalTaskError(f"Base video template missing for VDM Job {job_id}")
            # Download R2 key to /tmp/ so Stage 3 (Stream upload) has a local file.
            local_base = download_base_video_to_tmp(base_video_path)
            intermediate_files.append(local_base)
            final_video_path = local_base

        elif mode == "WithThanks":
            if is_card_only:
                card_r2_key = None
                if campaign and campaign.gratitude_video:
                    card_r2_key = campaign.gratitude_video.name
                if card_r2_key:
                    local_card = download_base_video_to_tmp(card_r2_key)
                    intermediate_files.append(local_card)
                    final_video_path = local_card
                # else None — template falls back to a default image
            else:
                is_personalized = campaign.is_personalized if campaign else False
                if is_personalized:
                    if not base_video_path:
                        raise FatalTaskError(
                            f"Base video template missing for stitching Job {job_id}"
                        )
                    if not client:
                        raise FatalTaskError(
                            f"Charity context missing for personalized delivery Job {job_id}"
                        )

                    raw_script = campaign.voiceover_script if campaign else ""

                    # Download base video from R2 to /tmp/.
                    local_base = download_base_video_to_tmp(base_video_path)
                    intermediate_files.append(local_base)

                    spec = VideoSpec(
                        donor_name=str(job.display_donor_name),
                        donation_amount=str(job.donation_amount),
                        charity_name=client.charity_name,
                        campaign_name=campaign.name if campaign else "",
                        voiceover_script=raw_script or None,
                        voice_id=(campaign.voice_id if campaign else "") or "",
                        base_video_path=local_base,
                    )
                    final_video_path, tts_path = build_personalized_video(spec)
                    intermediate_files.append(tts_path)

                    # Upload generated video to R2 immediately so Stage 3 retries are idempotent.
                    r2_url = upload_output_to_r2(
                        final_video_path,
                        f"videos/{os.path.basename(final_video_path)}",
                    )
                    job.video_path = r2_url
                    job.save(update_fields=["video_path"])

                    # VideoEvent created *after* successful generation.
                    VideoEvent.objects.create(job=job, campaign=campaign, event_type="GENERATED")

                else:
                    # Default (non-personalised) video.
                    if not base_video_path:
                        logger.warning(
                            "Job %s: base video missing for default mode — card-only fallback.",
                            job_id,
                        )
                        is_card_only = True
                        template_name = "withthanks_card_only.html"
                        card_r2_key = (
                            campaign.gratitude_video.name
                            if (campaign and campaign.gratitude_video)
                            else None
                        )
                        if card_r2_key:
                            local_card = download_base_video_to_tmp(card_r2_key)
                            intermediate_files.append(local_card)
                            final_video_path = local_card
                    else:
                        local_base = download_base_video_to_tmp(base_video_path)
                        intermediate_files.append(local_base)
                        final_video_path = local_base

    except FatalTaskError:
        with contextlib.suppress(Exception):
            job.status = "failed"
            job.error_message = traceback.format_exc()
            job.save(update_fields=["status", "error_message"])
        logger.error(
            "Job %s: fatal error in Stage 2 — not retrying.\n%s",
            job_id,
            traceback.format_exc(),
        )
        raise

    return {
        **context,
        "is_card_only": is_card_only,
        "template_name": template_name,
        "final_video_path": final_video_path,
        "intermediate_files": intermediate_files,
    }


# ---------------------------------------------------------------------------
# Stage 3 — Dispatch & Deliver Email
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=10, default_retry_delay=2, rate_limit="2/s", queue="default")
def dispatch_email_for_job(self, context):
    """
    Stage 3 of 3.  Stateless delivery step running on the *default* queue.

    Uploads to Cloudflare Stream (per-job, or cached for VDM), builds
    tracking URLs, renders the email template, and sends via Resend.

    Because Stage 2 already persisted ``job.video_path``, any retry here
    only repeats the delivery step — FFmpeg is never re-executed.
    """
    from django.template.loader import render_to_string

    from .services.sync_bridge import sync_job_to_normalized_models

    start_time = time.time()
    job_id = context["job_id"]
    mode = context["mode"]
    final_video_path = context.get("final_video_path")
    intermediate_files = context.get("intermediate_files", [])
    template_name = context["template_name"]
    image_url = context["image_url"]
    server_url = context["server_url"]
    is_card_only = context["is_card_only"]

    try:
        job = DonationJob.objects.select_related(
            "charity",
            "campaign",
            "campaign__charity",
            "donation_batch",
            "donation_batch__charity",
        ).get(id=job_id)
        client = resolve_job_charity(job)
        campaign = job.campaign

        if not client:
            raise FatalTaskError(f"Charity context missing for email delivery Job {job_id}")

        if mode == "VDM" and client and UnsubscribedUser.is_unsubscribed(job.email, client):
            generation_time = round(time.time() - start_time, 2)
            job.status = "skipped"
            job.error_message = (
                f"Suppressed VDM email to unsubscribed recipient {job.email} for "
                f"{client.charity_name}."
            )
            job.campaign_type = mode
            job.generation_time = generation_time
            job.completed_at = now()
            job.save(
                update_fields=[
                    "status",
                    "error_message",
                    "campaign_type",
                    "generation_time",
                    "completed_at",
                ]
            )

            all_tmp = list(intermediate_files)
            if final_video_path and final_video_path not in all_tmp:
                all_tmp.append(final_video_path)
            cleanup_intermediate(all_tmp, None)

            logger.info("Job %s skipped due to prior VDM unsubscribe for %s", job_id, job.email)
            return {"status": "skipped", "job_id": job_id}

        charity_logo_url = ""
        if client and client.logo:
            charity_logo_url = resolve_storage_video_url(
                storage_path=client.logo.name,
                server_url=server_url,
            )

        # --- Cloudflare Stream upload --------------------------------------- #
        if mode == "VDM":
            stream_delivery = (
                get_or_upload_campaign_stream(campaign, final_video_path)
                if campaign
                else StreamDelivery()
            )
        else:
            stream_delivery = (
                (
                    stream_safe_upload(final_video_path or "", meta_name=f"Job {job_id}")
                    or StreamDelivery()
                )
                if final_video_path
                else StreamDelivery()
            )

        if final_video_path and not stream_delivery.playback_url:
            raise FatalTaskError(
                f"Cloudflare Stream upload required for donor delivery on Job {job_id}."
            )

        cf_stream_url = stream_delivery.playback_url or None
        thumbnail_url = _resolve_email_thumbnail_url(
            mode=mode,
            image_path=image_url,
            server_url=server_url,
            stream_delivery=stream_delivery,
        )
        video_url_link = resolve_public_video_url(
            final_video_path=final_video_path,
            stream_delivery=stream_delivery,
            server_url=server_url,
            storage_video_path=job.video_path or context.get("base_video_path"),
        )

        # --- Tracking URLs -------------------------------------------------- #
        suppress_unsub = bool(campaign and campaign.is_thank_you)
        # --- EmailTracking record ------------------------------------------- #
        tracking_record, _ = EmailTracking.objects.get_or_create(
            job=job,
            defaults={
                "campaign": campaign,
                "batch": job.donation_batch,
                "user_id": job.id,
                "campaign_type": mode,
                "sent": True,
                "vdm": False,
            },
        )
        tracking = build_tracking_urls(
            job_id=job.id,
            mode=mode,
            server_url=server_url,
            tracking_token=build_tracking_token(tracking_id=tracking_record.id),
            campaign_id=campaign.id if campaign else None,
            batch_id=job.donation_batch.id if job.donation_batch else None,
            suppress_unsubscribe=suppress_unsub,
        )

        # --- SENT analytics event ------------------------------------------- #
        EmailEvent.objects.create(campaign=campaign, job=job, event_type="SENT")

        # --- Render template ------------------------------------------------ #
        email_context = {
            "greeting_line": build_email_greeting_line(job.display_donor_name),
            "donation_amount": job.donation_amount,
            "charity_name": client.charity_name,
            "charity_website_url": client.website_url,
            "charity_logo_url": charity_logo_url,
            "image_url": thumbnail_url,
            "video_url": video_url_link,
            "cf_stream_url": cf_stream_url,
            "primary_cta_url": tracking.click_url or cf_stream_url or video_url_link,
            "is_video_card": is_card_only,
            "campaign_name": campaign.name if campaign else "WithThanks Campaign",
            "unsubscribe_url": tracking.unsubscribe_url,
            "tracking_pixel_url": tracking.pixel_url,
            "tracking_click_url": tracking.click_url,
        }
        if mode == "VDM":
            email_context["email_body_paragraphs"] = build_email_paragraphs(
                campaign=campaign,
                job=job,
                charity_name=client.charity_name,
                default_body=DEFAULT_VDM_EMAIL_BODY,
            )
        else:
            default_body = (
                DEFAULT_CARD_ONLY_EMAIL_BODY if is_card_only else DEFAULT_THANK_YOU_EMAIL_BODY
            )
            email_context["email_body_paragraphs"] = build_email_paragraphs(
                campaign=campaign,
                job=job,
                charity_name=client.charity_name,
                default_body=default_body,
            )
        full_template_path = f"charity/email_templates/{template_name}"
        email_html = render_to_string(full_template_path, email_context)

        # --- Subject -------------------------------------------------------- #
        subject = resolve_email_subject(
            campaign=campaign, job=job, charity_name=client.charity_name
        )

        # --- Send via Resend ------------------------------------------------ #
        try:
            resend_response = send_video_email(
                to_email=job.email,
                file_path=None,
                job_id=str(job.id),
                donor_name=job.display_donor_name,
                donation_amount=job.donation_amount,
                from_email=resolve_sender_email(
                    campaign=campaign,
                    charity_name=client.charity_name if client else None,
                ),
                charity_name=client.charity_name,
                subject=subject,
                video_url=video_url_link,
                is_card_only=is_card_only,
                html=email_html,
            )
            # Persist Resend message ID so webhook events can be correlated back
            resend_id: str | None = None
            if isinstance(resend_response, dict):
                _id = resend_response.get("id")
                if isinstance(_id, str) and _id:
                    resend_id = _id
            else:
                _id = getattr(resend_response, "id", None)
                # In tests/mocks this can be a MagicMock; only accept real strings
                if isinstance(_id, str) and _id:
                    resend_id = _id
            if resend_id:
                job.resend_message_id = resend_id
        except Exception as send_exc:
            job.status = "failed"
            job.error_message = f"Resend failed: {send_exc!s}"
            job.save(update_fields=["status", "error_message"])
            EmailEvent.objects.create(job=job, campaign=campaign, event_type="FAILED")
            logger.error("Job %s Resend failure: %s", job_id, send_exc)
            cleanup_intermediate(intermediate_files, final_video_path)
            raise self.retry(exc=send_exc) from send_exc

        # --- Success -------------------------------------------------------- #
        generation_time = round(time.time() - start_time, 2)
        job.status = "success"
        # Persist the hosted playback URL so tracking redirects always send
        # donors to the same Stream URL that was embedded in the email.
        if video_url_link:
            job.video_path = video_url_link
        job.campaign_type = mode
        job.generation_time = generation_time
        job.completed_at = now()
        job.save()

        # Clean up ALL /tmp/ files — intermediate TTS, downloaded base copies, and
        # generated output (already uploaded to R2/Stream before this point).
        # final_video_path is added to the list so it is also removed.
        all_tmp = list(intermediate_files)
        if final_video_path and final_video_path not in all_tmp:
            all_tmp.append(final_video_path)
        cleanup_intermediate(all_tmp, None)

        logger.info("✅ Job %s success in %ss", job_id, generation_time)
        sync_job_to_normalized_models(job)
        return {"status": "success", "job_id": job_id}

    except FatalTaskError as exc:
        # Unrecoverable — mark failed, do not retry
        with contextlib.suppress(Exception):
            j = DonationJob.objects.get(id=job_id)
            if j.status != "failed":
                j.status = "failed"
                j.error_message = str(exc)
                j.save(update_fields=["status", "error_message"])
        return {"status": "failed", "job_id": job_id}

    except Exception as exc:
        logger.error("❌ Job %s Stage-3 failure: %s\n%s", job_id, exc, traceback.format_exc())
        already_failed = False
        with contextlib.suppress(Exception):
            j = DonationJob.objects.get(id=job_id)
            already_failed = j.status == "failed"
            if not already_failed:
                j.status = "failed"
                j.error_message = str(exc)
                j.save(update_fields=["status", "error_message"])

        cleanup_intermediate(intermediate_files, None)

        # Guard: if already explicitly marked failed (e.g. after a Resend
        # inner-retry exhaustion) don't loop further.
        if already_failed:
            return {"status": "failed", "job_id": job_id}

        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Batch completion callback (chord header callback)
# ---------------------------------------------------------------------------


@shared_task(queue="default")
def on_batch_complete(job_results, *, batch_id):
    """
    Chord callback fired after *all* per-job chains in a batch have finished.

    ``job_results`` is kept in the signature for Celery chord compatibility
    but its contents are intentionally ignored — counts are derived directly
    from the DB so that large batches don't push a huge result list through
    Redis.
    """
    from django.core.mail import send_mail

    try:
        batch = DonationBatch.objects.select_related("charity").get(id=batch_id)
    except DonationBatch.DoesNotExist:
        logger.error("on_batch_complete: DonationBatch %s not found", batch_id)
        return

    # Count directly from DB — authoritative source of truth
    counts = (
        DonationJob.objects.filter(donation_batch_id=batch_id)
        .values("status")
        .annotate(n=Count("id"))
    )
    status_map = {row["status"]: row["n"] for row in counts}
    total = sum(status_map.values())
    failed = status_map.get("failed", 0)

    new_status = (
        DonationBatch.BatchStatus.COMPLETED_WITH_ERRORS
        if failed
        else DonationBatch.BatchStatus.COMPLETED
    )
    batch.status = new_status
    batch.save(update_fields=["status"])

    logger.info(
        "Batch %s completed — total=%d failed=%d status=%s",
        batch_id,
        total,
        failed,
        new_status,
    )

    # Admin notification via Django email backend
    admin_email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", None)
    if admin_email:
        charity_name = batch.charity.charity_name if batch.charity else "Unknown"
        subject = f"[WithThanks] Batch #{batch.batch_number} complete — {charity_name}"
        body = (
            f"Batch #{batch.batch_number} for {charity_name} has finished.\n"
            f"Total jobs : {total}\n"
            f"Failed     : {failed}\n"
            f"Status     : {new_status}\n"
        )
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [admin_email])
        except Exception as mail_err:
            logger.warning("on_batch_complete: admin email failed: %s", mail_err)

    return {"batch_id": batch_id, "total": total, "failed": failed, "status": new_status}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def batch_process_csv(self, batch_id):
    """
    Scalable CSV processor: reads the CSV file, bulk-creates DonationJob rows,
    then fans them out as a Celery group with an on_batch_complete chord
    callback so the batch status is updated atomically when all jobs finish.
    """
    try:
        batch = DonationBatch.objects.select_related("charity", "campaign").get(id=batch_id)
        client = batch.charity
        campaign = batch.campaign

        if campaign and campaign.is_vdm and not campaign.vdm_video:
            logger.error(
                "Batch %s: VDM campaign %s is missing vdm_video; failing preflight.",
                batch_id,
                campaign.id,
            )
            batch.status = DonationBatch.BatchStatus.FAILED
            batch.save(update_fields=["status"])
            return

        # Mark batch as processing before dispatching workers
        batch.status = DonationBatch.BatchStatus.PROCESSING
        batch.save(update_fields=["status"])

        from django.core.files.storage import default_storage

        try:
            csv_binary = default_storage.open(batch.csv_filename, "rb")
        except (FileNotFoundError, Exception) as exc:
            logger.error(
                "Batch %s: CSV file not found in storage (%s): %s",
                batch_id,
                batch.csv_filename,
                exc,
            )
            batch.status = DonationBatch.BatchStatus.FAILED
            batch.save(update_fields=["status"])
            return

        with io.TextIOWrapper(csv_binary, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

            jobs_to_create = []
            for row in reader:
                recipient_parts = extract_csv_recipient_parts(row, default="Donor")
                name = (
                    build_vdm_recipient_name(row, default="Donor")
                    if campaign and campaign.is_vdm
                    else build_csv_recipient_name(row, default="Donor")
                )
                email = get_csv_row_value(
                    row,
                    "email",
                    "recipient email",
                    "email-id",
                    "email address",
                )
                amount = (
                    get_csv_row_value(
                        row,
                        "donation_amount",
                        "amount",
                        "donation",
                    )
                    or "0"
                )

                if not email:
                    continue

                jobs_to_create.append(
                    DonationJob(
                        donor_name=name,
                        donor_title=recipient_parts["donor_title"],
                        donor_first_name=recipient_parts["donor_first_name"],
                        donor_last_name=recipient_parts["donor_last_name"],
                        donation_amount=amount,
                        email=email.strip(),
                        status="pending",
                        charity=client,
                        campaign=campaign,
                        donation_batch=batch,
                    )
                )

        if not jobs_to_create:
            logger.warning("Batch %s: no valid rows found in CSV", batch_id)
            batch.status = DonationBatch.BatchStatus.COMPLETED
            batch.save(update_fields=["status"])
            return

        # Bulk-create all jobs in one DB round-trip, retrieve their IDs
        created_jobs = DonationJob.objects.bulk_create(jobs_to_create)
        job_ids = [j.id for j in created_jobs]

        # Fan out as a group of per-job chains; on_batch_complete fires once
        # all chains finish and collects the Stage-3 result from each.
        header = group(
            chain(
                validate_and_prep_job.s(jid).set(queue="default"),
                generate_video_for_job.s().set(queue="video"),
                dispatch_email_for_job.s().set(queue="default"),
            )
            for jid in job_ids
        )
        callback = on_batch_complete.s(batch_id=batch_id).set(queue="default")
        chord(header)(callback)

        logger.info("Batch %s: dispatched %d jobs via chord", batch_id, len(job_ids))

    except Exception as exc:
        logger.error("batch_process_csv %s failed: %s\n%s", batch_id, exc, traceback.format_exc())
        with contextlib.suppress(Exception):
            DonationBatch.objects.filter(id=batch_id).update(
                status=DonationBatch.BatchStatus.FAILED
            )
        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Periodic tasks (called by Celery Beat — see withthanks/celery.py)
# ---------------------------------------------------------------------------


@shared_task
def refresh_all_campaign_stats():
    """Refresh materialized CampaignStats for all campaigns."""
    from .services.analytics_service import rebuild_all_campaign_stats

    return rebuild_all_campaign_stats()


@shared_task(queue="default")
def async_refresh_campaign_stats(campaign_id: str) -> bool:
    """Refresh CampaignStats for a single campaign. Called from webhook handlers."""
    from .analytics_models import CampaignStats
    from .models import Campaign

    try:
        campaign = Campaign.objects.get(id=campaign_id)
        stats, _ = CampaignStats.objects.get_or_create(campaign=campaign)
        stats.update_stats()
        return True
    except Campaign.DoesNotExist:
        return False


@shared_task
def mark_overdue_invoices():
    """Transition Sent invoices past their due date to Overdue status."""
    from .services.invoice_service import mark_overdue_bulk

    return mark_overdue_bulk()


@shared_task
def cleanup_stale_jobs():
    """Reset jobs stuck in 'processing' for over 2 hours back to 'failed'."""
    from .services.batch_service import reset_stale_jobs

    return reset_stale_jobs()


@shared_task
def prune_voiceover_cache():
    """Delete voiceover cache files older than 30 days."""
    from .services.cleanup_service import prune_voiceover_cache as _prune

    return _prune()


@shared_task
def cleanup_old_videos():
    """Delete generated video files from VIDEO_OUTPUT_DIR older than 7 days."""
    from .services.cleanup_service import remove_old_videos

    return remove_old_videos()


# ---------------------------------------------------------------------------
# CRM Sync — Blackbaud Raiser's Edge NXT
# ---------------------------------------------------------------------------


@shared_task(queue="maintenance")
def sync_crm_donations():
    """
    Fan-out task: find all charities with Blackbaud enabled and dispatch
    an individual sync task for each.  Runs on the *maintenance* queue via
    django-celery-beat (recommended cadence: every hour).
    """
    from .models import Charity

    charity_ids = list(Charity.objects.filter(blackbaud_enabled=True).values_list("id", flat=True))
    if not charity_ids:
        logger.info("sync_crm_donations: no charities with Blackbaud enabled")
        return {"dispatched": 0}

    for charity_id in charity_ids:
        sync_charity_blackbaud.apply_async(args=(charity_id,), queue="default")

    logger.info("sync_crm_donations: dispatched sync for %d charities", len(charity_ids))
    return {"dispatched": len(charity_ids)}


@shared_task(bind=True, queue="default", max_retries=3, default_retry_delay=300)
def sync_charity_blackbaud(self, charity_id: int):
    """
    Pull new donations from Blackbaud Raiser's Edge NXT for a single charity
    and create DonationJob records (+ fire the video/email pipeline) for each.

    Uses ``blackbaud_last_synced_at`` as an incremental cursor.  Falls back
    to 24 hours ago if no prior sync has been recorded.
    """
    from decimal import Decimal

    from .models import Campaign, Charity, DonationBatch, DonationJob
    from .utils.crm_adapters.base import CRMError
    from .utils.crm_adapters.blackbaud import BlackbaudAdapter

    try:
        charity = Charity.objects.get(id=charity_id)
    except Charity.DoesNotExist:
        logger.error("sync_charity_blackbaud: charity %s not found", charity_id)
        return

    if not charity.blackbaud_enabled:
        logger.info(
            "sync_charity_blackbaud: charity %s has Blackbaud disabled — skipping", charity_id
        )
        return

    # Determine sync window start
    since = charity.blackbaud_last_synced_at or (now() - timedelta(hours=24))

    logger.info(
        "sync_charity_blackbaud: starting sync for charity %s since %s",
        charity_id,
        since.isoformat(),
    )

    try:
        adapter = BlackbaudAdapter(charity)
        donations = adapter.fetch_new_donations(since=since)
    except CRMError as exc:
        logger.exception("CRM fetch failed for charity %s: %s", charity_id, exc)
        raise self.retry(exc=exc) from exc

    if not donations:
        logger.info("sync_charity_blackbaud: no new donations for charity %s", charity_id)
        charity.blackbaud_last_synced_at = now()
        charity.save(update_fields=["blackbaud_last_synced_at"])
        return {"charity_id": charity_id, "created": 0}

    # Resolve the active campaign for thank-you sends
    campaign = (
        Campaign.objects.accepting_donations()
        .filter(
            charity=charity,
            campaign_type=Campaign.CampaignType.THANK_YOU,
        )
        .first()
    )

    batch = DonationBatch.objects.create(
        charity=charity,
        campaign=campaign,
        batch_number=DonationBatch.get_next_batch_number(charity),
        campaign_name=f"Blackbaud Sync \u2014 {now().strftime('%Y-%m-%d %H:%M')}",
        status=DonationBatch.BatchStatus.PROCESSING,
    )

    created_count = 0
    for donation in donations:
        try:
            amount = Decimal(str(donation.get("amount", "0")))
        except Exception:
            amount = Decimal("0")

        job = DonationJob.objects.create(
            donor_name=donation.get("donor_name", ""),
            email=donation.get("donor_email", ""),
            donation_amount=amount,
            status="pending",
            charity=charity,
            campaign=campaign,
            donation_batch=batch,
        )

        chain(
            validate_and_prep_job.s(job.id).set(queue="default"),
            generate_video_for_job.s().set(queue="video"),
            dispatch_email_for_job.s().set(queue="default"),
        ).apply_async()

        created_count += 1

    # Advance the sync cursor
    charity.blackbaud_last_synced_at = now()
    charity.save(update_fields=["blackbaud_last_synced_at"])

    logger.info(
        "sync_charity_blackbaud: created %d jobs for charity %s",
        created_count,
        charity_id,
    )
    return {"charity_id": charity_id, "created": created_count, "batch_id": batch.id}
