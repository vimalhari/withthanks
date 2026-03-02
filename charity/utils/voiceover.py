import hashlib
import os
from pathlib import Path
import logging
from django.conf import settings
from elevenlabs.client import ElevenLabs

# Setup logger
logger = logging.getLogger(__name__)

# ElevenLabs API credentials

API_KEY = settings.ELEVENLABS_API_KEY
VOICE_ID = settings.ELEVENLABS_VOICE_ID

# Initialize ElevenLabs client
client = ElevenLabs(api_key=API_KEY)

# Cache directory for generated voiceovers
VOICEOVER_CACHE_DIR = getattr(settings, "VOICEOVER_CACHE_DIR", Path(settings.MEDIA_ROOT) / "voiceover_cache")
if not VOICEOVER_CACHE_DIR.is_dir():
    try:
        os.makedirs(VOICEOVER_CACHE_DIR, exist_ok=True)
    except Exception as e:
        logger.warning(f"Failed to create voiceover cache directory {VOICEOVER_CACHE_DIR}: {e}")

def generate_voiceover(text: str, file_name: str, voice_id: str = None) -> str:
    """
    Generate TTS audio from ElevenLabs and save as MP3, using a cache to avoid duplicate work.
    Returns the path to the saved MP3 file.
    """
    # Use provided voice_id or fallback to settings
    target_voice_id = voice_id or VOICE_ID
    
    # Compute a deterministic hash based on the text and voice ID
    hash_input = f"{target_voice_id}:{text}".encode("utf-8")
    text_hash = hashlib.sha256(hash_input).hexdigest()[:16]
    cache_file = Path(VOICEOVER_CACHE_DIR) / f"{text_hash}.mp3"

    if cache_file.exists():
        logger.info("Reusing cached voiceover: %s", cache_file)
        return str(cache_file)

    try:
        # Ensure output directory exists (fallback if cache dir missing)
        output_dir = Path(settings.MEDIA_ROOT) / "voiceovers"
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"{file_name}.mp3"

        logger.debug("Generating voiceover for file: %s", file_path)

        # Generate voiceover using ElevenLabs
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=target_voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128"
        )

        # Save MP3 file in chunks
        with open(file_path, "wb") as f:
            for chunk in audio_generator:
                f.write(chunk)

        logger.info("Voiceover successfully saved: %s", file_path)
        # Copy to cache for future reuse
        try:
            os.replace(file_path, cache_file)
            logger.debug("Cached voiceover at %s", cache_file)
        except Exception as e:
            logger.warning(f"Failed to cache voiceover: {e}")
        return str(cache_file)

    except Exception as e:
        logger.exception("Failed to generate voiceover: %s", e)
        raise RuntimeError(f"Voiceover generation failed: {e}") from e
