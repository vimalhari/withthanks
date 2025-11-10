import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def _run(cmd):
    logger.debug("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("ffmpeg command failed: %s", proc.stderr)
        raise RuntimeError(proc.stderr)
    return proc

def stitch_voice_and_overlay(
    input_video: str,
    tts_wav: str,
    overlay_text: str,
    out_filename: str,
    intro_duration: float = 5,
    output_dir: str | Path = None
):
    """
    Creates a video where:
    - first `intro_duration` seconds: overlay + TTS
    - remaining video: original video & audio
    """
    input_video = Path(input_video)
    tts_wav = Path(tts_wav)
    output_dir = Path(output_dir or Path.cwd())
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / out_filename

    # Step 1: make TTS exactly intro_duration
    trimmed_audio = output_dir / f"{out_filename}_tts.wav"
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(tts_wav),
        "-t", str(intro_duration),
        "-ar", "48000", "-ac", "2",
        str(trimmed_audio)
    ])

    # Step 2: create first intro_duration seconds video with overlay text at bottom
      # Step 2: create first intro_duration seconds video with overlay text at bottom in big, bold, centered style
    intro_video = output_dir / f"{out_filename}_intro.mp4"
    # Update the fontfile path to a valid bold font on your system
    bold_font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  

    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_video),
        "-t", str(intro_duration),
        "-vf", (
            f"drawtext=text='{overlay_text}':"
            "fontcolor=white:"
            "fontsize=40:"
            f"fontfile={bold_font_path}:"
            "x=(w-text_w)/2:"
            "y=h-text_h-100:"  # 100 px padding from bottom
            "box=1:"
            "boxcolor=black@0.7:"  # darker box for stronger contrast
            "boxborderw=15"       # thicker border for bigger padding around text
        ),
        "-an",
        str(intro_video)
    ])


    # Step 3: trim remaining video
    remaining_video = output_dir / f"{out_filename}_rest.mp4"
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_video),
        "-ss", str(intro_duration),
        "-c", "copy",
        str(remaining_video)
    ])

    # Step 4: combine intro video + TTS + remaining video
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(intro_video),
        "-i", str(trimmed_audio),
        "-i", str(remaining_video),
        "-filter_complex",
        "[0:v][1:a][2:v][2:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path)
    ])

    # Cleanup intermediate files (optional)
    for tmp in [trimmed_audio, intro_video, remaining_video]:
        try:
            tmp.unlink()
        except Exception:
            pass

    return str(output_path)
