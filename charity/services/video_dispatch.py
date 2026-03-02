from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from charity.models import Campaign, Charity, Donation, Donor, VideoSendLog
from charity.utils.cloudflare_stream import StreamUploadResult, upload_video_to_stream
from charity.utils.filenames import safe_filename
from charity.utils.resend_utils import send_video_email
from charity.utils.video_utils import stitch_voice_and_overlay
from charity.utils.voiceover import generate_voiceover

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


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


def _render_template(body: str, context: dict[str, Any]) -> str:
    if not body:
        return ""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key, "")
        return str(value)

    return PLACEHOLDER_PATTERN.sub(replace, body)


def _default_personalized_text(donor_name: str, amount: Decimal) -> str:
    return (
        f"Hi {donor_name}, thank you for your donation of {amount} euros! "
        "We really appreciate your support."
    )


def _default_gratitude_text(donor_name: str) -> str:
    return (
        f"Hi {donor_name}, thank you again for your continued support. "
        "Your repeated generosity means a lot to us."
    )


def _resolve_campaign(charity: Charity, campaign_type: str) -> Campaign:
    campaign = (
        Campaign.objects.filter(
            charity=charity,
            campaign_type=campaign_type,
            is_active=True,
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
    context = {
        "donor_name": donor_name,
        "donation_amount": donation_amount,
        "charity": charity_name,
        "campaign_name": campaign.name,
    }

    if gratitude_mode:
        text = _default_gratitude_text(donor_name)
    elif campaign.text_template and campaign.text_template.body:
        text = _render_template(campaign.text_template.body, context)
    else:
        text = _default_personalized_text(donor_name, donation_amount)

    file_base = safe_filename(f"{donor_name}_{donation_amount}_{timezone.now().timestamp()}")[:120]

    voiceover_path = generate_voiceover(text=text, file_name=file_base)

    if campaign.video_template and campaign.video_template.video_file:
        input_video = campaign.video_template.video_file.path
    else:
        input_video = str(settings.BASE_VIDEO_PATH)

    output_path = stitch_voice_and_overlay(
        input_video=input_video,
        tts_wav=voiceover_path,
        overlay_text=text,
        out_filename=f"{file_base}.mp4",
        output_dir=settings.VIDEO_OUTPUT_DIR,
        intro_duration=5,
    )
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

    # ------------------------------------------------------------------ #
    # Upload to Cloudflare Stream (when enabled).                          #
    # On failure we log a warning and fall back to attachment delivery.    #
    # ------------------------------------------------------------------ #
    stream_result: StreamUploadResult | None = None
    if getattr(settings, "CLOUDFLARE_STREAM_ENABLED", False):
        try:
            stream_result = upload_video_to_stream(
                video_path,
                meta_name=f"{charity.name} – {donor.email}",
            )
        except Exception as stream_exc:  # noqa: BLE001
            logger.warning(
                "Cloudflare Stream upload failed for %s – falling back to attachment: %s",
                donor.email,
                stream_exc,
            )

    try:
        provider_resp = send_video_email(
            to_email=donor.email,
            file_path=video_path,
            playback_url=stream_result.playback_url if stream_result else "",
            thumbnail_url=stream_result.thumbnail_url if stream_result else "",
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
