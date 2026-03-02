import subprocess
from pathlib import Path
import logging
import time
from django.conf import settings

logger = logging.getLogger(__name__)


def escape_drawtext(text: str) -> str:
    """Escape text for FFmpeg drawtext inside double quotes."""
    return (
        text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace(":", "\\:")
            .replace(",", "\\,")
            .replace("!", "\\!")
            .replace("%", "\\%")
    )


def fix_windows_fontpath(font: str) -> str:
    """FFmpeg requires C\\:/Windows/... format."""
    if ":" in font:
        drive, rest = font.split(":", 1)
        return f"{drive}\\:/{rest.lstrip('/')}"
    return font


def stitch_voice_and_overlay(
    input_video: str,
    tts_mp3: str,
    overlay_text: str,
    out_filename: str,
    output_dir: str | Path,
    intro_duration: float = 5,
    logo_path: str = None,
    overlay_spec: dict = None
):
    start_time = time.perf_counter()  # ⏱ Start timer

    spec = overlay_spec or {}
    intro_duration = spec.get("intro_duration", intro_duration)
    fontsize = spec.get("fontsize", 44)
    fontcolor = spec.get("fontcolor", "white")
    x_pos = spec.get("x", "(w-text_w)/2")
    y_pos = spec.get("y", "h-text_h-180")
    box = spec.get("box", 1)
    boxcolor = spec.get("boxcolor", "black@0.6")
    boxborderw = spec.get("boxborderw", 15)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / out_filename

    # If input_video is absolute, use it; otherwise assume relative to BASE_VIDEO_PATH's parent or similar
    # The original code assumed relative to settings.MEDIA_ROOT/base_videos
    # We'll stick to that logic unless it looks like an absolute path
    if Path(input_video).is_absolute():
       input_video_path = Path(input_video)
    else:
       input_video_path = Path(settings.MEDIA_ROOT) / "base_videos" / input_video
       
    tts_mp3_path = Path(tts_mp3)

    if not input_video_path.exists():
        raise FileNotFoundError(f"Base video missing: {input_video_path}")
    if not tts_mp3_path.exists():
        raise FileNotFoundError(f"TTS file missing: {tts_mp3_path}")

    safe_text = escape_drawtext(overlay_text)

    font_candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    font = next((p for p in font_candidates if Path(p).exists()), "")

    if font:
        font = fix_windows_fontpath(font)
        font_arg = f"fontfile='{font}':"
    else:
        font_arg = ""

    # ---------------------------------------------------------
    # FFmpeg Filter Complex Construction
    # ---------------------------------------------------------
    
    # 1. Base split logic
    fc = f"[0:v]scale=1280:-2,split[v_intro_raw][v_rest];"
    
    # 2. Intro trim & Drawtext (Captions)
    fc += (
        f"[v_intro_raw]trim=0:{intro_duration},setpts=PTS-STARTPTS,"
        f"drawtext=text=\"{safe_text}\":{font_arg}"
        f"fontsize={fontsize}:fontcolor={fontcolor}:x={x_pos}:y={y_pos}:"
        f"box={box}:boxcolor={boxcolor}:boxborderw={boxborderw}[v_intro_text];"
    )
    
    # 3. Logo Overlay (Conditional)
    if logo_path and Path(logo_path).exists():
        # Input 2 will be the logo
        # Scale logo to width 150px (auto height)
        fc += f"[2:v]scale=150:-1[logo_scaled];"
        # Overlay top-right with 20px padding
        fc += f"[v_intro_text][logo_scaled]overlay=main_w-overlay_w-20:20[v_intro_done];"
    else:
        # No logo, just pass through
        fc += f"[v_intro_text]copy[v_intro_done];"

    # 4. Rest of video trim
    fc += f"[v_rest]trim=start={intro_duration},setpts=PTS-STARTPTS[v_rest_done];"

    # 5. Audio trims
    fc += f"[1:a]atrim=0:{intro_duration},asetpts=PTS-STARTPTS[a_intro];"
    fc += f"[0:a]atrim=start={intro_duration},asetpts=PTS-STARTPTS[a_rest];"

    # 6. Concatenation
    fc += "[v_intro_done][v_rest_done]concat=n=2:v=1:a=0[v];"
    fc += "[a_intro][a_rest]concat=n=2:v=0:a=1[a]"

    # Build FFmpeg command
    video_encoder = "h264_nvenc" if getattr(settings, "USE_GPU", False) else "libx264"
    preset = "ultrafast" if not getattr(settings, "USE_GPU", False) else "fast"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_video_path),
        "-i", str(tts_mp3_path),
    ]

    # Add logo input if exists
    if logo_path and Path(logo_path).exists():
        cmd.extend(["-i", str(logo_path)])

    cmd.extend([
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", video_encoder, "-preset", preset, "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(final_path),
    ])

    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        logger.error(proc.stderr)
        raise RuntimeError(proc.stderr)

    end_time = time.perf_counter()
    time_taken = round(end_time - start_time, 3)

    return str(final_path), time_taken


def get_video_duration_ffmpeg(video_path: str | Path) -> float:
    """
    Get the duration of a video file using ffprobe.
    Returns duration in seconds as a float.
    """
    cmd = [
        "ffprobe", 
        "-v", "error", 
        "-show_entries", "format=duration", 
        "-of", "default=noprint_wrappers=1:nokey=1", 
        str(video_path)
    ]
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return 0.0


def merge_video_audio_no_reencode(
    video_input: str | Path,
    audio_input: str | Path,
    output_path: str | Path
) -> str:
    """
    Merges audio into video with ZERO re-encoding of the video stream.
    Replaces original audio fully. Uses shortest duration.
    """
    import subprocess
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_input),
        "-i", str(audio_input),
        "-c:v", "copy",       # No re-encoding of video
        "-c:a", "aac",        # Encode audio to AAC for MP4 compatibility
        "-map", "0:v:0",      # Use first video stream
        "-map", "1:a:0",      # Use first audio stream (from audio input)
        "-shortest",          # Use shortest duration
        str(output_path)
    ]
    
    logger.info(f"🚀 Running FFmpeg (No Re-encode): {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        logger.error(f"FFmpeg failed: {result.stderr}")
        raise RuntimeError(f"FFmpeg merge failed: {result.stderr}")
        
    return str(output_path)
