# charity/utils/voiceover.py
from elevenlabs.client import ElevenLabs
from pathlib import Path
from django.conf import settings

API_KEY = "sk_785d9fcecb467873a281f9fcd9fde07794da1d30e15c3be2"
VOICE_ID = "9rh371MqHF5jaDZ7VPvk"

client = ElevenLabs(api_key=API_KEY)

def generate_voiceover(text: str, file_name: str) -> str:
    output_dir = Path(settings.MEDIA_ROOT) / "voiceovers"
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{file_name}.mp3"

    # Get generator from ElevenLabs
    audio_generator = client.text_to_speech.convert(
        text=text,
        voice_id=VOICE_ID,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128"
    )

    # Write generator chunks to file
    with open(file_path, "wb") as f:
        for chunk in audio_generator:
            f.write(chunk)

    return str(file_path)
