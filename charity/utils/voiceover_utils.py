from __future__ import annotations

import contextlib
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

_R2_CACHE_PREFIX = "voiceover_cache"


def _download_r2_cache_to_tmp(r2_key: str, tmp_path: str) -> bool:
    """
    Check R2 for a cached voiceover matching *r2_key*.

    If found, stream it to *tmp_path* and return ``True``.
    Returns ``False`` when there is no cached object.
    """
    from django.core.files.storage import default_storage

    if not default_storage.exists(r2_key):
        return False
    logger.info("Voiceover cache hit (R2): %s → %s", r2_key, tmp_path)
    with default_storage.open(r2_key, "rb") as src, open(tmp_path, "wb") as dst:
        dst.write(src.read())
    return True


def _generate_and_upload_voiceover(
    text: str,
    target_voice_id: str,
    r2_key: str,
    tmp_path: str,
    api_key: str,
) -> None:
    """
    Call the ElevenLabs API, write the audio to *tmp_path*, and upload
    the result to R2 at *r2_key* for future cache hits.
    """
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from elevenlabs.client import ElevenLabs

    tmp_gen_path = f"{tmp_path}.gen"
    try:
        client = ElevenLabs(api_key=api_key)
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=target_voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        with open(tmp_gen_path, "wb") as f:
            for chunk in audio_generator:
                f.write(chunk)

        with open(tmp_gen_path, "rb") as f:
            r2_filename = r2_key.rsplit("/", 1)[-1]
            default_storage.save(r2_key, ContentFile(f.read(), name=r2_filename))
        logger.debug("Voiceover cached in R2: %s", r2_key)

        os.replace(tmp_gen_path, tmp_path)
    except Exception:
        if os.path.exists(tmp_gen_path):
            with contextlib.suppress(Exception):
                os.remove(tmp_gen_path)
        raise


def generate_voiceover(text: str, file_name: str, voice_id: str | None = None) -> str:
    """
    Generate TTS audio from ElevenLabs and return a local ``/tmp/`` path.

    Cache strategy (R2-backed, cloud-native):
    - Compute ``sha256(voice_id + ":" + text)[:16]`` → R2 key
      ``voiceover_cache/<hash>.mp3``
    - Cache hit  → stream R2 object to ``/tmp/<hash>.mp3`` and return that path.
    - Cache miss → generate via ElevenLabs API to ``/tmp/<uuid>.mp3``,
      upload to R2 at the cache key, return the ``/tmp/`` path.

    The caller (FFmpeg task) is responsible for deleting the returned ``/tmp/``
    file after it has been consumed.  Nothing is ever written to MEDIA_ROOT.
    """
    from django.conf import settings

    api_key: str = getattr(settings, "ELEVENLABS_API_KEY", "") or os.environ.get(
        "ELEVENLABS_API_KEY", ""
    )
    default_voice_id: str = getattr(settings, "ELEVENLABS_VOICE_ID", "") or os.environ.get(
        "ELEVENLABS_VOICE_ID", ""
    )
    target_voice_id = voice_id or default_voice_id

    hash_input = f"{target_voice_id}:{text}".encode()
    text_hash = hashlib.sha256(hash_input).hexdigest()[:16]
    r2_key = f"{_R2_CACHE_PREFIX}/{text_hash}.mp3"
    tmp_path = f"/tmp/{text_hash}.mp3"

    if _download_r2_cache_to_tmp(r2_key, tmp_path):
        return tmp_path

    try:
        _generate_and_upload_voiceover(text, target_voice_id, r2_key, tmp_path, api_key)
    except Exception as exc:
        logger.exception("Failed to generate voiceover: %s", exc)
        raise RuntimeError(f"Voiceover generation failed: {exc}") from exc

    logger.info("Voiceover generated and cached: %s", tmp_path)
    return tmp_path
