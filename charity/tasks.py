import os
import logging
import traceback
import time
import tempfile
from datetime import timedelta
from django.utils.timezone import now
from celery import shared_task
from django.conf import settings
from django.urls import reverse
from .models import DonationJob, Charity, UnsubscribedUser, DonationBatch, EmailTracking
from .models_analytics import EmailEvent, VideoEvent
import csv
from charity.utils.media_utils import extract_blob_to_temp
from .utils.voiceover import generate_voiceover
from .utils.video_utils import stitch_voice_and_overlay
from .utils.resend_utils import send_video_email
from .utils.filenames import safe_filename

logger = logging.getLogger(__name__)


def cleanup_intermediate(files, final_file):
    """Delete TTS and temporary files after final video is ready."""
    for f in files:
        if f and os.path.exists(f) and f != final_file:
            try:
                os.remove(f)
            except Exception as err:
                logger.warning(f"Failed to delete file {f}: {err}")


@shared_task(bind=True, max_retries=10, default_retry_delay=2, rate_limit='2/s')
def process_donation_row(self, job_id):
    """
    STRICT PROCESSING PIPELINE: VDM vs WithThanks
    """
    from django.template.loader import render_to_string # Import here to avoid circular imports if any

    start_time = time.time()
    intermediate_files = []
    
    try:
        # Fetch Job with related Client (Charity) and Campaign
        job = DonationJob.objects.select_related('charity', 'campaign', 'donation_batch').get(id=job_id)
        client = job.charity
        campaign = job.campaign
        
        # 1. CHECK UNSUBSCRIBE STATUS FIRST
        if UnsubscribedUser.is_unsubscribed(job.email, client):
            logger.info(f"Skipping Job {job.id}: User {job.email} is unsubscribed from {client.organization_name}")
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
        VideoEvent.objects.create(
            job=job,
            campaign=campaign,
            event_type='generated'
        )

        if not base_video_path and client.default_template_video:
            base_video_path = client.default_template_video.path
            
        # LOGIC BRANCHING
        final_video_path = None
        is_card_only = False
        template_name = "withthanks.html" # Default
        image_url = f"{settings.MEDIA_URL}email_templates/thankyou.png" # Default image

        # Ensure MEDIA_URL is absolute or handled correctly by the client
        # For email templates, we often need a full URL if images are hosted, 
        # or just the path if the email client resolves it (unlikely without full URL).
        # Assuming there's a SERVER_BASE_URL to prepend.
        server_url = getattr(settings, "SERVER_BASE_URL", "https://hirefella.com").rstrip('/')
        full_image_url = f"{server_url}{image_url}"
        
        if mode == "VDM":
            # MODE 1: VDM (Video Direct Marketing)
            # - No personalization
            # - No voice generation
            # - Just send default video
            # - Use vdm.html
            
            if not base_video_path or not os.path.exists(base_video_path):
                 raise FileNotFoundError(f"Base video template missing for VDM Job {job.id}")
            
            final_video_path = base_video_path
            template_name = "vdm.html"
            image_url = f"{settings.MEDIA_URL}email_templates/vdm_banner.png"
            full_image_url = f"{server_url}{image_url}"
            
            unsubscribe_path = reverse('unsubscribe', kwargs={'job_id': job.id})
            unsubscribe_url = f"{server_url}{unsubscribe_path}"

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
                 try:
                     image_url = campaign.image_banner.url
                 except Exception:
                     pass
            
            full_image_url = f"{server_url}{image_url}"

        elif mode == "WithThanks":
            # MODE 2: WithThanks
            # Check 30-day deduplication FIRST
            
            thirty_days_ago = now() - timedelta(days=30)
            
            # Check if this email received a SUCCESSFUL video in last 30 days
            has_recent_video = DonationJob.objects.filter(
                charity=client,
                email=job.email,
                status='success',
                completed_at__gte=thirty_days_ago
            ).exists()
            
            if has_recent_video or (job.media_type_override == 'image'):
                # DEDUPLICATED -> Send Card Only
                logger.info(f"Job {job.id}: 30-day deduplication or override triggering Card-Only mode.")
                is_card_only = True
                
                # Use Gratitude Asset if available (Prioritize Campaign)
                if campaign and campaign.gratitude_video:
                    final_video_path = campaign.gratitude_video.path
                    logger.info(f"Job {job.id}: Using campaign gratitude asset: {final_video_path}")
                elif client.gratitude_card:
                    final_video_path = client.gratitude_card.path
                    logger.info(f"Job {job.id}: Using specific client gratitude card: {final_video_path}")
                else:
                    final_video_path = None # Fallback to default image in template if no card uploaded
                    
                template_name = "withthanks_card_only.html"
                image_url = f"{settings.MEDIA_URL}email_templates/thankyou.png"
                full_image_url = f"{server_url}{image_url}"
                
            else:
                # Check Personalization
                is_personalized = False
                template_name = "withthanks.html"
                image_url = f"{settings.MEDIA_URL}email_templates/thankyou.png" # Same image for both personalized/default logic
                full_image_url = f"{server_url}{image_url}"

                if campaign:
                    is_personalized = campaign.is_personalized
                
                if is_personalized:
                    # PERSONALIZED FLOW
                    # 1. Resolve Script
                    raw_script = ""
                    if campaign and campaign.voiceover_script_override:
                        raw_script = campaign.voiceover_script_override
                    else:
                        raw_script = client.default_voiceover_script
                        
                    # 2. Resolve Voice
                    voice_id = client.default_voice_id
                    
                    # 3. Personalize Text
                    personalized_script = raw_script.replace("{{donor_name}}", str(job.donor_name)) \
                                                    .replace("{{donation_amount}}", str(job.donation_amount)) \
                                                    .replace("{{organization_name}}", str(client.organization_name))
                    
                    # 4. Generate Voice (TTS)
                    file_base = safe_filename(f"voice_{job.id}")
                    tts_path = generate_voiceover(
                        text=personalized_script, 
                        file_name=file_base, 
                        voice_id=voice_id
                    )
                    intermediate_files.append(tts_path)
                    
                    # 5. Stitch Video
                    if not base_video_path or not os.path.exists(base_video_path):
                        raise FileNotFoundError(f"Base video template missing for stitching Job {job.id}")
                        
                    output_filename = f"final_video_{job.id}.mp4"
                    
                    final_video_path, _ = stitch_voice_and_overlay(
                        input_video=base_video_path,
                        tts_mp3=tts_path,
                        overlay_text="", 
                        out_filename=output_filename,
                        output_dir=settings.VIDEO_OUTPUT_DIR,
                        logo_path=None 
                    )
                    
                else:
                    # NOT PERSONALIZED -> Send Default Video
                    if not base_video_path or not os.path.exists(base_video_path):
                        logger.warning(f"Base video template missing for Default Video Job {job.id}. Falling back to Card Only.")
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
        tracking_record, created = EmailTracking.objects.get_or_create(
            job=job,
            defaults={
                'campaign': campaign,
                'batch': job.donation_batch,
                'user_id': job.id,
                'appeal_type': mode,
                'sent': True, # Assume sent if we get to this point (will be saved shortly)
                'vdm': False
            }
        )
        
        # Log SENT event for analytics
        EmailEvent.objects.create(campaign=campaign, job=job, event_type='SENT')

        # TRACKING: Generate URLs
        # Base Params: c=campaign_id, b=batch_id, u=job_id, type=appeal_type
        # We use job.id (u) as the primary key for lookup in views as it's unique enough and linked to everything.
        
        # 1. Tracking Pixel URL
        # Path: /track/open/?c=...&b=...&u=...&type=...
        track_open_path = reverse('track_open')
        pixel_url = f"{server_url}{track_open_path}?u={job.id}&type={mode}"
        if campaign: pixel_url += f"&c={campaign.id}"
        if job.donation_batch: pixel_url += f"&b={job.donation_batch.id}"

        # 2. Click/Redirect URL (Wraps the video/image link)
        # Path: /track/click/?u=...&type=...
        track_click_path = reverse('track_click')
        click_url = f"{server_url}{track_click_path}?u={job.id}&type={mode}"
        if campaign: click_url += f"&c={campaign.id}"
        if job.donation_batch: click_url += f"&b={job.donation_batch.id}"

        # 3. Unsubscribe URL
        # Path: /track/unsubscribe/?u=...&type=...
        # STRICT LOGIC: Omit for THANKYOU campaigns
        unsubscribe_url = None
        if campaign and campaign.appeal_type != 'THANKYOU':
            track_unsub_path = reverse('track_unsubscribe_full')
            unsubscribe_url = f"{server_url}{track_unsub_path}?u={job.id}&type={mode}"


        # 4. Resolve Public Video Link for Template
        video_url_link = ""
        if final_video_path:
            try:
                rel_path = os.path.relpath(final_video_path, settings.MEDIA_ROOT)
                clean_rel_path = rel_path.replace("\\", "/")
                # Ensure we don't have double slashes in the path part, but preserve protocol
                m_url = settings.MEDIA_URL
                if not m_url.startswith('/'): m_url = '/' + m_url
                
                # Combine correctly: server_url (no trailing slash) + m_url (leading slash) + clean_rel_path
                video_url_link = f"{server_url}{m_url}{clean_rel_path}".replace("//", "/").replace("http:/", "http://").replace("https:/", "https://")
            except ValueError:
                video_url_link = f"{server_url}/media/outputs/{os.path.basename(final_video_path)}"

        context = {
            'donor_name': job.donor_name,
            'donation_amount': job.donation_amount,
            'organization_name': client.organization_name,
            'from_email': client.contact_email,
            'image_url': full_image_url,
            'video_url': video_url_link, # Pass raw video link for reference, but template likely uses click_url
            'is_video_card': is_card_only, # Fixed: was is_video_card (undefined)
            'campaign_name': campaign.name if campaign else "WithThanks Campaign",
            'unsubscribe_url': unsubscribe_url, # Now available for both modes if needed
            
            # New Tracking Context
            'tracking_pixel_url': pixel_url,
            'tracking_click_url': click_url,
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
                html=email_html # Pass rendered HTML
            )
            # Log successful sent event
            EmailEvent.objects.create(
                job=job,
                campaign=campaign,
                event_type='sent'
            )
        except Exception as e:
            job.status = "failed"
            job.error_message = f"Resend failed: {str(e)}"
            job.save()
            # Log failed event
            EmailEvent.objects.create(
                job=job,
                campaign=campaign,
                event_type='failed'
            )
            logger.error(f"Job {job_id} Resend failure: {e}")
            cleanup_intermediate(intermediate_files, final_video_path)
            # Re-raising allows Celery retry
            raise e

        # SUCCESS
        generation_time = round(time.time() - start_time, 2)
        job.status = "success"
        job.video_path = final_video_path if final_video_path else "" 
        job.appeal_type = mode # Save mode to job
        
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
        raise self.retry(exc=exc)


@shared_task
def batch_process_csv(batch_id):
    """
    Scalable CSV processor: reads file and triggers individual jobs.
    """
    try:
        batch = DonationBatch.objects.select_related('charity', 'campaign').get(id=batch_id)
        client = batch.charity
        campaign = batch.campaign
        
        # Resolve CSV path (Assuming it was saved to media)
        # Using a safer approach with the file on disk
        from django.core.files.storage import default_storage
        file_path = default_storage.path(batch.csv_filename) if not os.path.isabs(batch.csv_filename) else batch.csv_filename
        
        if not os.path.exists(file_path):
            logger.error(f"Batch {batch_id}: CSV file not found at {file_path}")
            return
            
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            # Normalize headers
            if reader.fieldnames:
                reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
            
            count = 0
            for i, row in enumerate(reader, start=1):
                # Flexible mapping
                name = row.get("donor_name") or row.get("name") or row.get("full name") or "Donor"
                email = row.get("email") or row.get("recipient email") or row.get("email-id") or row.get("email address")
                amount = row.get("donation_amount") or row.get("amount") or row.get("donation") or "0"
                
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
