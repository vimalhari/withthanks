import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_cache_dir() -> Path:
    """Return the voiceover cache directory, creating it on first access."""
    from django.conf import settings

    cache_dir = Path(
        getattr(settings, "VOICEOVER_CACHE_DIR", Path(settings.MEDIA_ROOT) / "voiceover_cache")
    )
    if not cache_dir.is_dir():
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("Failed to create voiceover cache directory %s: %s", cache_dir, exc)
    return cache_dir


def generate_voiceover(text: str, file_name: str, voice_id: str | None = None) -> str:
    """
    Generate TTS audio from ElevenLabs and save as MP3, using a cache to avoid duplicate work.

    All settings reads happen inside this function so that importing this
    module never triggers ``AppRegistryNotReady`` or ``ImproperlyConfigured``.

    Returns the path to the saved MP3 file.
    """
    from django.conf import settings
    from elevenlabs.client import ElevenLabs

    api_key: str = getattr(settings, "ELEVENLABS_API_KEY", "") or os.environ.get(
        "ELEVENLABS_API_KEY", ""
    )
    default_voice_id: str = getattr(settings, "ELEVENLABS_VOICE_ID", "") or os.environ.get(
        "ELEVENLABS_VOICE_ID", ""
    )
    target_voice_id = voice_id or default_voice_id

    cache_dir = _get_cache_dir()

    # Compute a deterministic hash based on the text and voice ID.
    hash_input = f"{target_voice_id}:{text}".encode()
    text_hash = hashlib.sha256(hash_input).hexdigest()[:16]
    cache_file = cache_dir / f"{text_hash}.mp3"

    if cache_file.exists():
        logger.info("Reusing cached voiceover: %s", cache_file)
        return str(cache_file)

    try:
        output_dir = Path(settings.MEDIA_ROOT) / "voiceovers"
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{file_name}.mp3"

        logger.debug("Generating voiceover for file: %s", file_path)

        elevenlabs_client = ElevenLabs(api_key=api_key)
        audio_generator = elevenlabs_client.text_to_speech.convert(
            text=text,
            voice_id=target_voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        with open(file_path, "wb") as f:
            for chunk in audio_generator:
                f.write(chunk)

        logger.info("Voiceover successfully saved: %s", file_path)
        try:
            os.replace(file_path, cache_file)
            logger.debug("Cached voiceover at %s", cache_file)
        except Exception as exc:
            logger.warning("Failed to cache voiceover: %s", exc)
        return str(cache_file)

    except Exception as exc:
        logger.exception("Failed to generate voiceover: %s", exc)
        raise RuntimeError(f"Voiceover generation failed: {exc}") from exc
