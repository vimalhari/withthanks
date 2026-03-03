"""
Shared video production service.

Pure functions that handle TTS generation and FFmpeg stitching without any
model or ORM dependencies.  Both the CSV batch pipeline (``tasks.py``) and the
API pipeline (``video_dispatch_service.py``) delegate their video work here so that
production logic is defined in exactly one place.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.utils import timezone

from charity.utils.filenames import safe_filename
from charity.utils.video_utils import stitch_voice_and_overlay
from charity.utils.voiceover_utils import generate_voiceover

if TYPE_CHECKING:
    from decimal import Decimal

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def render_script(body: str, context: dict[str, Any]) -> str:
    """Replace ``{{ key }}`` placeholders in *body* with values from *context*."""
    if not body:
        return ""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(context.get(key, ""))

    return PLACEHOLDER_PATTERN.sub(_replace, body)


# ---------------------------------------------------------------------------
# Default text generators
# ---------------------------------------------------------------------------


def default_personalized_text(donor_name: str, amount: Decimal | str) -> str:
    return (
        f"Hi {donor_name}, thank you for your donation of {amount} euros! "
        "We really appreciate your support."
    )


def default_gratitude_text(donor_name: str) -> str:
    return (
        f"Hi {donor_name}, thank you again for your continued support. "
        "Your repeated generosity means a lot to us."
    )


# ---------------------------------------------------------------------------
# Input spec for video production
# ---------------------------------------------------------------------------


@dataclass
class VideoSpec:
    """All the parameters needed to produce a personalised donor video."""

    donor_name: str
    donation_amount: Decimal | str
    charity_name: str
    campaign_name: str = ""
    voiceover_script: str | None = None
    voice_id: str = ""
    base_video_path: str | None = None
    gratitude_mode: bool = False
    intro_duration: float = 5
    overlay_text: str | None = field(default=None)
    logo_path: str | None = None


# ---------------------------------------------------------------------------
# Core video production
# ---------------------------------------------------------------------------


def build_personalized_video(spec: VideoSpec) -> tuple[str, str]:
    """
    Produce a personalized donor video.

    Returns ``(output_video_path, voiceover_path)`` so callers can clean up
    intermediate files.
    """
    context = {
        "donor_name": spec.donor_name,
        "donation_amount": spec.donation_amount,
        "charity": spec.charity_name,
        "organization_name": spec.charity_name,
        "campaign_name": spec.campaign_name,
    }

    # --- Resolve voiceover text ----------------------------------------- #
    if spec.voiceover_script:
        text = render_script(spec.voiceover_script, context)
    elif spec.gratitude_mode:
        text = default_gratitude_text(spec.donor_name)
    else:
        text = default_personalized_text(spec.donor_name, spec.donation_amount)

    # --- Resolve base video --------------------------------------------- #
    input_video = spec.base_video_path or str(settings.BASE_VIDEO_PATH)

    # --- Generate TTS --------------------------------------------------- #
    file_base = safe_filename(
        f"{spec.donor_name}_{spec.donation_amount}_{timezone.now().timestamp()}"
    )[:120]

    voiceover_path = generate_voiceover(
        text=text, file_name=file_base, voice_id=spec.voice_id,
    )

    # --- Stitch video --------------------------------------------------- #
    output_path, _elapsed = stitch_voice_and_overlay(
        input_video=input_video,
        tts_mp3=voiceover_path,
        overlay_text=spec.overlay_text if spec.overlay_text is not None else text,
        out_filename=f"{file_base}.mp4",
        output_dir=settings.VIDEO_OUTPUT_DIR,
        intro_duration=spec.intro_duration,
        logo_path=spec.logo_path,
    )

    return output_path, voiceover_path
