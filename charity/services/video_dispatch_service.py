from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass, field
from datetime import timedelta
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
    """
    Download a campaign template video from R2 to a ``/tmp/`` path and return it.

    The caller is responsible for deleting the returned path after use.
    """
    from charity.utils.video_utils import download_base_video_to_tmp

    template_obj = (
        campaign.gratitude_video_template if use_gratitude_template else campaign.video_template
    )
    if not template_obj or not template_obj.video_file:
        raise ValueError("Campaign template video is not configured.")
    r2_key = template_obj.video_file.name
    return download_base_video_to_tmp(r2_key)


def _resolve_script_and_voice(campaign: Campaign, gratitude_mode: bool) -> tuple[str | None, str]:
    """Return ``(voiceover_script, voice_id)`` for the given campaign mode."""
    if gratitude_mode or not campaign.text_template:
        return None, getattr(campaign.text_template, "voice_id", "") if campaign.text_template else ""
    if campaign.text_template.body:
        return campaign.text_template.body, campaign.text_template.voice_id or ""
    return None, ""


def _build_personalized_video(
    *,
    donor_name: str,
    donation_amount: Decimal,
    charity_name: str,
    campaign: Campaign,
    gratitude_mode: bool,
) -> tuple[str, str]:
    """
    Build a personalised donor video.

    Returns ``(tmp_video_path, r2_url)``:
    - ``tmp_video_path`` — local ``/tmp/`` path for Stream upload / email attachment.
    - ``r2_url`` — permanent cloud URL stored in ``VideoSendLog.video_file``.

    The caller is responsible for deleting ``tmp_video_path`` after use.
    """
    from charity.utils.video_utils import download_base_video_to_tmp, upload_output_to_r2

    script, voice_id = _resolve_script_and_voice(campaign, gratitude_mode)

    if not (campaign.video_template and campaign.video_template.video_file):
        raise ValueError("Campaign has no video template configured.")
    local_base = download_base_video_to_tmp(campaign.video_template.video_file.name)

    spec = VideoSpec(
        donor_name=donor_name,
        donation_amount=donation_amount,
        charity_name=charity_name,
        campaign_name=campaign.name,
        voiceover_script=script,
        voice_id=voice_id,
        base_video_path=local_base,
        gratitude_mode=gratitude_mode,
    )

    try:
        output_path, voiceover_path = build_personalized_video(spec)
    finally:
        with contextlib.suppress(Exception):
            os.remove(local_base)

    r2_url = upload_output_to_r2(
        output_path,
        f"videos/{os.path.basename(output_path)}",
    )

    with contextlib.suppress(Exception):
        os.remove(voiceover_path)

    return output_path, r2_url


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
            tmp_video_path = _build_template_video_path(campaign, use_gratitude_template=True)
            r2_video_url = tmp_video_path  # template videos already live in R2; use tmp path for delivery
        else:
            send_kind = VideoSendLog.SendKind.GRATITUDE
            tmp_video_path, r2_video_url = _build_personalized_video(
                donor_name=donor.full_name or donor.email,
                donation_amount=amount,
                charity_name=charity.name,
                campaign=campaign,
                gratitude_mode=True,
            )
    elif campaign.video_mode == Campaign.VideoMode.TEMPLATE:
        send_kind = VideoSendLog.SendKind.TEMPLATE
        tmp_video_path = _build_template_video_path(campaign, use_gratitude_template=False)
        r2_video_url = tmp_video_path
    else:
        send_kind = VideoSendLog.SendKind.PERSONALIZED
        tmp_video_path, r2_video_url = _build_personalized_video(
            donor_name=donor.full_name or donor.email,
            donation_amount=amount,
            charity_name=charity.name,
            campaign=campaign,
            gratitude_mode=False,
        )

    # Upload to Cloudflare Stream (when enabled).
    stream_result = stream_safe_upload(
        tmp_video_path,
        meta_name=f"{charity.name} - {donor.email}",
    )

    try:
        provider_resp = send_video_email(
            to_email=donor.email,
            file_path=tmp_video_path,
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
            video_file=r2_video_url,
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
            video_file=r2_video_url,
            stream_video_id=stream_result.video_id if stream_result else "",
            stream_playback_url=stream_result.playback_url if stream_result else "",
            stream_thumbnail_url=stream_result.thumbnail_url if stream_result else "",
            error_message=str(exc),
        )
        raise
    finally:
        # Always clean up the /tmp/ copy — the durable copy is in R2/Stream.
        with contextlib.suppress(Exception):
            os.remove(tmp_video_path)

    return DispatchResult(
        donation_id=donation.id,
        send_log_id=log.id,
        donor_email=donor.email,
        send_kind=send_kind,
        campaign_type=campaign_type,
        video_path=r2_video_url,
        stream_video_id=stream_result.video_id if stream_result else "",
        stream_playback_url=stream_result.playback_url if stream_result else "",
    )
