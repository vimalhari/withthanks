from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from charity.models import Campaign, Charity, Donation, Donor, VideoSendLog
from charity.services.video_build_service import VideoSpec, build_personalized_video
from charity.services.video_pipeline_service import stream_safe_upload
from charity.utils.resend_utils import send_video_email

logger = logging.getLogger(__name__)

@dataclass
class DispatchResult:
    donation_id: int
    send_log_id: int
    donor_email: str
    send_kind: str
    campaign_type: str
    video_path: str
    stream_video_id: str = field(default="")
    stream_playback_url: str = field(default="")


def _resolve_campaign(charity: Charity, campaign_type: str) -> Campaign:
    campaign = (
        Campaign.objects.filter(
            client=charity,
            campaign_type=campaign_type,
            status="active",
        )
        .select_related("text_template", "video_template", "gratitude_video_template")
        .first()
    )
    if not campaign:
        raise ValueError(f"No active campaign found for charity={charity.id} type={campaign_type}")
    return campaign


def _should_send_gratitude(
    *,
    donor: Donor,
    charity: Charity,
    campaign: Campaign,
    donated_at,
) -> bool:
    latest_personalized_send = (
        VideoSendLog.objects.filter(
            donor=donor,
            charity=charity,
            status=VideoSendLog.Status.SENT,
            campaign_type=Campaign.CampaignType.THANK_YOU,
            send_kind=VideoSendLog.SendKind.PERSONALIZED,
        )
        .order_by("-sent_at")
        .first()
    )

    if not latest_personalized_send:
        return False

    sent_at = latest_personalized_send.sent_at
    within_window = (
        sent_at <= donated_at <= sent_at + timedelta(days=campaign.gratitude_cooldown_days)
    )
    return bool(within_window)


def _build_template_video_path(campaign: Campaign, use_gratitude_template: bool) -> str:
    template_obj = (
        campaign.gratitude_video_template if use_gratitude_template else campaign.video_template
    )
    if not template_obj or not template_obj.video_file:
        raise ValueError("Campaign template video is not configured.")
    return str(Path(template_obj.video_file.path))


def _build_personalized_video(
    *,
    donor_name: str,
    donation_amount: Decimal,
    charity_name: str,
    campaign: Campaign,
    gratitude_mode: bool,
) -> str:
    # Resolve script & voice from the campaign's text template
    if gratitude_mode:
        script = None  # builder will use default gratitude text
        voice_id = getattr(campaign.text_template, "voice_id", "") if campaign.text_template else ""
    elif campaign.text_template and campaign.text_template.body:
        script = campaign.text_template.body
        voice_id = campaign.text_template.voice_id or ""
    else:
        script = None  # builder will use default personalized text
        voice_id = ""

    # Resolve base video
    if campaign.video_template and campaign.video_template.video_file:
        base_video = campaign.video_template.video_file.path
    else:
        base_video = None  # builder falls back to settings.BASE_VIDEO_PATH

    spec = VideoSpec(
        donor_name=donor_name,
        donation_amount=donation_amount,
        charity_name=charity_name,
        campaign_name=campaign.name,
        voiceover_script=script,
        voice_id=voice_id,
        base_video_path=base_video,
        gratitude_mode=gratitude_mode,
    )
    output_path, _voiceover_path = build_personalized_video(spec)
    return output_path


@transaction.atomic
def dispatch_donation_video(
    *,
    charity: Charity,
    donor_email: str,
    donor_name: str,
    amount: Decimal,
    donated_at=None,
    source: str = "API",
    campaign_type: str = Campaign.CampaignType.THANK_YOU,
) -> DispatchResult:
    donated_at = donated_at or timezone.now()
    campaign = _resolve_campaign(charity, campaign_type)

    donor, _ = Donor.objects.get_or_create(
        charity=charity,
        email=donor_email.strip().lower(),
        defaults={"full_name": donor_name.strip()},
    )
    if donor_name and donor.full_name != donor_name:
        donor.full_name = donor_name.strip()
        donor.save(update_fields=["full_name"])

    donation = Donation.objects.create(
        donor=donor,
        charity=charity,
        amount=amount,
        donated_at=donated_at,
        campaign_type=campaign_type,
        source=source,
    )

    gratitude_mode = campaign_type == Campaign.CampaignType.THANK_YOU and _should_send_gratitude(
        donor=donor, charity=charity, campaign=campaign, donated_at=donated_at
    )

    if gratitude_mode:
        if campaign.gratitude_video_template:
            send_kind = VideoSendLog.SendKind.GRATITUDE
            video_path = _build_template_video_path(campaign, use_gratitude_template=True)
        else:
            send_kind = VideoSendLog.SendKind.GRATITUDE
            video_path = _build_personalized_video(
                donor_name=donor.full_name or donor.email,
                donation_amount=amount,
                charity_name=charity.name,
                campaign=campaign,
                gratitude_mode=True,
            )
    elif campaign.video_mode == Campaign.VideoMode.TEMPLATE:
        send_kind = VideoSendLog.SendKind.TEMPLATE
        video_path = _build_template_video_path(campaign, use_gratitude_template=False)
    else:
        send_kind = VideoSendLog.SendKind.PERSONALIZED
        video_path = _build_personalized_video(
            donor_name=donor.full_name or donor.email,
            donation_amount=amount,
            charity_name=charity.name,
            campaign=campaign,
            gratitude_mode=False,
        )

    # Upload to Cloudflare Stream (when enabled).
    # stream_safe_upload handles the CLOUDFLARE_STREAM_ENABLED guard,
    # logs a warning on failure, and returns None for attachment fallback.
    stream_result = stream_safe_upload(
        video_path,
        meta_name=f"{charity.name} - {donor.email}",
    )

    try:
        provider_resp = send_video_email(
            to_email=donor.email,
            file_path=video_path,
            job_id=str(donation.id),
            donor_name=donor.full_name or donor.email,
            donation_amount=str(amount),
            organization_name=charity.name,
        )
        message_id = provider_resp.get("id", "") if isinstance(provider_resp, dict) else ""
        log = VideoSendLog.objects.create(
            charity=charity,
            donor=donor,
            donation=donation,
            campaign=campaign,
            campaign_type=campaign_type,
            send_kind=send_kind,
            status=VideoSendLog.Status.SENT,
            recipient_email=donor.email,
            video_file=video_path,
            stream_video_id=stream_result.video_id if stream_result else "",
            stream_playback_url=stream_result.playback_url if stream_result else "",
            stream_thumbnail_url=stream_result.thumbnail_url if stream_result else "",
            provider_message_id=message_id,
        )
    except Exception as exc:
        log = VideoSendLog.objects.create(
            charity=charity,
            donor=donor,
            donation=donation,
            campaign=campaign,
            campaign_type=campaign_type,
            send_kind=send_kind,
            status=VideoSendLog.Status.FAILED,
            recipient_email=donor.email,
            video_file=video_path,
            stream_video_id=stream_result.video_id if stream_result else "",
            stream_playback_url=stream_result.playback_url if stream_result else "",
            stream_thumbnail_url=stream_result.thumbnail_url if stream_result else "",
            error_message=str(exc),
        )
        raise

    return DispatchResult(
        donation_id=donation.id,
        send_log_id=log.id,
        donor_email=donor.email,
        send_kind=send_kind,
        campaign_type=campaign_type,
        video_path=video_path,
        stream_video_id=stream_result.video_id if stream_result else "",
        stream_playback_url=stream_result.playback_url if stream_result else "",
    )
