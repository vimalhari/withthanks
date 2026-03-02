# charity/utils/voiceover.py
from __future__ import annotations

import logging
import os
from pathlib import Path

from django.conf import settings
from elevenlabs.client import ElevenLabs

logger = logging.getLogger(__name__)

# Fallback voice used when neither the TextTemplate nor ELEVENLABS_DEFAULT_VOICE_ID is set.
_FALLBACK_VOICE_ID = "9rh371MqHF5jaDZ7VPvk"


def _get_client() -> ElevenLabs:
    """Return an ElevenLabs client using the API key from settings / env."""
    api_key: str = getattr(settings, "ELEVENLABS_API_KEY", "") or os.environ.get(
        "ELEVENLABS_API_KEY", ""
    )
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is not set. Add it to your .env file or environment."
        )
    return ElevenLabs(api_key=api_key)


def generate_voiceover(text: str, file_name: str, *, voice_id: str = "") -> str:
    """Generate an MP3 voiceover from *text* using ElevenLabs TTS.

    Args:
        text:     The script to synthesise.
        file_name: Base filename (without extension) for the output MP3.
        voice_id: ElevenLabs voice ID. Falls back to ``settings.ELEVENLABS_DEFAULT_VOICE_ID``
                  and then to the module-level default if not supplied.

    Returns:
        Absolute path to the generated ``.mp3`` file.
    """
    resolved_voice_id = (
        voice_id
        or getattr(settings, "ELEVENLABS_DEFAULT_VOICE_ID", "")
        or _FALLBACK_VOICE_ID
    )

    output_dir = Path(settings.MEDIA_ROOT) / "voiceovers"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{file_name}.mp3"

    client = _get_client()
    audio_generator = client.text_to_speech.convert(
        text=text,
        voice_id=resolved_voice_id,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    with open(file_path, "wb") as fh:
        for chunk in audio_generator:
            fh.write(chunk)

    logger.debug("Voiceover saved to %s (voice=%s)", file_path, resolved_voice_id)
    return str(file_path)
