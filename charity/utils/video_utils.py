import contextlib
import json
import logging
import subprocess
import textwrap
import time
import uuid
from pathlib import Path

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
    logo_path: str | None = None,
    overlay_spec: dict | None = None,
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

    # input_video must always be an absolute local path (guaranteed by download_base_video_to_tmp).
    input_video_path = Path(input_video)
    if not input_video_path.is_absolute():
        raise ValueError(
            f"stitch_voice_and_overlay requires an absolute input_video path, got: {input_video!r}. "
            "Call download_base_video_to_tmp() first to fetch the file from R2 into /tmp/."
        )

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
    fc = "[0:v]scale=1280:-2,split[v_intro_raw][v_rest];"

    # 2. Intro trim & Drawtext (Captions)
    fc += (
        f"[v_intro_raw]trim=0:{intro_duration},setpts=PTS-STARTPTS,"
        f'drawtext=text="{safe_text}":{font_arg}'
        f"fontsize={fontsize}:fontcolor={fontcolor}:x={x_pos}:y={y_pos}:"
        f"box={box}:boxcolor={boxcolor}:boxborderw={boxborderw}[v_intro_text];"
    )

    # 3. Logo Overlay (Conditional)
    if logo_path and Path(logo_path).exists():
        # Input 2 will be the logo
        # Scale logo to width 150px (auto height)
        fc += "[2:v]scale=150:-1[logo_scaled];"
        # Overlay top-right with 20px padding
        fc += "[v_intro_text][logo_scaled]overlay=main_w-overlay_w-20:20[v_intro_done];"
    else:
        # No logo, just pass through
        fc += "[v_intro_text]copy[v_intro_done];"

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
        "-i",
        str(input_video_path),
        "-i",
        str(tts_mp3_path),
    ]

    # Add logo input if exists
    if logo_path and Path(logo_path).exists():
        cmd.extend(["-i", str(logo_path)])

    cmd.extend(
        [
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            video_encoder,
            "-preset",
            preset,
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(final_path),
        ]
    )

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
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return 0.0


def _parse_frame_rate(raw_value: str | None) -> float:
    if not raw_value:
        return 30.0

    try:
        numerator, denominator = raw_value.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return 30.0
        return float(numerator) / denominator_value
    except Exception:
        with contextlib.suppress(Exception):
            return float(raw_value)
        return 30.0


def _probe_media_streams(media_path: str | Path) -> dict[str, int | float | str]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-of",
        "json",
        str(media_path),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])

    video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video_stream or not audio_stream:
        raise ValueError(f"Expected video and audio streams in {media_path}")

    return {
        "width": int(video_stream.get("width") or 1280),
        "height": int(video_stream.get("height") or 720),
        "fps": _parse_frame_rate(
            video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")
        ),
        "pix_fmt": str(video_stream.get("pix_fmt") or "yuv420p"),
        "video_codec": str(video_stream.get("codec_name") or ""),
        "sample_rate": int(audio_stream.get("sample_rate") or 48000),
        "channels": int(audio_stream.get("channels") or 2),
        "audio_codec": str(audio_stream.get("codec_name") or ""),
    }


def _build_drawtext_lines(text: str) -> str:
    wrapped = textwrap.fill(text.strip(), width=28) if text.strip() else ""
    return escape_drawtext(wrapped).replace("\n", r"\n")


def _select_intro_video_encoder(video_codec: str) -> str:
    if video_codec and video_codec != "h264":
        raise ValueError(
            "Personalized intro prepend requires H.264 template videos for stream-copy concat. "
            f"Found codec: {video_codec or 'unknown'}"
        )

    if getattr(settings, "USE_GPU", False):
        return "h264_nvenc"
    return "libx264"


def _select_intro_audio_encoder(audio_codec: str) -> str:
    if audio_codec and audio_codec != "aac":
        raise ValueError(
            "Personalized intro prepend requires AAC template audio for stream-copy concat. "
            f"Found codec: {audio_codec or 'unknown'}"
        )
    return "aac"


def generate_intro_clip(
    *,
    template_video: str | Path,
    tts_mp3: str | Path,
    caption_text: str,
    out_filename: str,
    output_dir: str | Path,
    logo_path: str | None = None,
    overlay_spec: dict | None = None,
) -> str:
    """
    Build a short intro clip for the donor-specific TTS.

    The intro is encoded to match the base template's stream parameters closely
    enough that it can be concatenated in front of the template without
    re-encoding the full template video.
    """
    template_path = Path(template_video)
    tts_path = Path(tts_mp3)
    if not template_path.exists():
        raise FileNotFoundError(f"Template video missing: {template_path}")
    if not tts_path.exists():
        raise FileNotFoundError(f"TTS file missing: {tts_path}")

    stream_info = _probe_media_streams(template_path)
    duration = max(get_video_duration_ffmpeg(tts_path) + 0.25, 0.5)
    fps = round(float(stream_info["fps"]), 3)
    width = int(stream_info["width"])
    height = int(stream_info["height"])

    spec = overlay_spec or {}
    fontsize = spec.get("fontsize", 44)
    fontcolor = spec.get("fontcolor", "white")
    x_pos = spec.get("x", "(w-text_w)/2")
    y_pos = spec.get("y", "h-text_h-180")
    box = spec.get("box", 1)
    boxcolor = spec.get("boxcolor", "black@0.6")
    boxborderw = spec.get("boxborderw", 15)
    bg_color = spec.get("background", "black")

    safe_text = _build_drawtext_lines(caption_text)
    font_candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    font = next((candidate for candidate in font_candidates if Path(candidate).exists()), "")
    font_arg = f"fontfile='{fix_windows_fontpath(font)}':" if font else ""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    intro_path = output_dir / out_filename

    filter_complex = [
        (
            f'[0:v]drawtext=text="{safe_text}":{font_arg}'
            f"fontsize={fontsize}:fontcolor={fontcolor}:x={x_pos}:y={y_pos}:"
            f"box={box}:boxcolor={boxcolor}:boxborderw={boxborderw}[v_text]"
        )
    ]
    final_video_label = "[v_text]"

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={bg_color}:s={width}x{height}:r={fps}:d={duration}",
        "-i",
        str(tts_path),
    ]

    if logo_path and Path(logo_path).exists():
        cmd.extend(["-i", str(logo_path)])
        filter_complex.append("[2:v]scale=150:-1[logo_scaled]")
        filter_complex.append("[v_text][logo_scaled]overlay=main_w-overlay_w-20:20[v_out]")
        final_video_label = "[v_out]"

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_complex),
            "-map",
            final_video_label,
            "-map",
            "1:a:0",
            "-c:v",
            _select_intro_video_encoder(str(stream_info["video_codec"])),
            "-preset",
            "fast" if getattr(settings, "USE_GPU", False) else "ultrafast",
            "-pix_fmt",
            str(stream_info["pix_fmt"]),
            "-c:a",
            _select_intro_audio_encoder(str(stream_info["audio_codec"])),
            "-ar",
            str(stream_info["sample_rate"]),
            "-ac",
            str(stream_info["channels"]),
            "-shortest",
            "-movflags",
            "+faststart",
            str(intro_path),
        ]
    )

    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        logger.error(proc.stderr)
        raise RuntimeError(proc.stderr)

    return str(intro_path)


def concat_intro_to_base(
    *,
    intro_clip: str | Path,
    base_video: str | Path,
    out_filename: str,
    output_dir: str | Path,
) -> str:
    """Prepend an intro clip to the base template without re-encoding the template."""
    intro_path = Path(intro_clip)
    base_path = Path(base_video)
    if not intro_path.exists():
        raise FileNotFoundError(f"Intro clip missing: {intro_path}")
    if not base_path.exists():
        raise FileNotFoundError(f"Base video missing: {base_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / out_filename
    concat_file = output_dir / f"{final_path.stem}_concat.txt"
    concat_file.write_text(
        f"file '{intro_path.as_posix()}'\nfile '{base_path.as_posix()}'\n",
        encoding="utf-8",
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(final_path),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    with contextlib.suppress(Exception):
        concat_file.unlink()

    if proc.returncode != 0:
        logger.error(proc.stderr)
        raise RuntimeError(proc.stderr)

    return str(final_path)


def merge_video_audio_no_reencode(
    video_input: str | Path, audio_input: str | Path, output_path: str | Path
) -> str:
    """
    Merges audio into video with ZERO re-encoding of the video stream.
    Replaces original audio fully. Uses shortest duration.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_input),
        "-i",
        str(audio_input),
        "-c:v",
        "copy",  # No re-encoding of video
        "-c:a",
        "aac",  # Encode audio to AAC for MP4 compatibility
        "-map",
        "0:v:0",  # Use first video stream
        "-map",
        "1:a:0",  # Use first audio stream (from audio input)
        "-shortest",  # Use shortest duration
        str(output_path),
    ]

    logger.info(f"🚀 Running FFmpeg (No Re-encode): {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"FFmpeg failed: {result.stderr}")
        raise RuntimeError(f"FFmpeg merge failed: {result.stderr}")

    return str(output_path)


# ---------------------------------------------------------------------------
# Stateless-worker helpers — R2-backed base-video download / output upload
# ---------------------------------------------------------------------------


def download_base_video_to_tmp(base_video_path: str) -> str:
    """
    Stream a base video from R2 (via ``default_storage``) into a unique
    ``/tmp/`` file and return that path for FFmpeg to consume.

    R2 is unconditionally the storage backend — there is no local-filesystem
    fallback.  Every Celery worker downloads the file fresh on each task so
    that no shared volume mount is required.
    """
    from django.core.files.storage import default_storage

    tmp_path = f"/tmp/{uuid.uuid4().hex}_base.mp4"
    logger.info("Downloading base video from R2: %s → %s", base_video_path, tmp_path)
    with default_storage.open(base_video_path, "rb") as src, open(tmp_path, "wb") as dst:
        dst.write(src.read())
    return tmp_path


def upload_output_to_r2(local_path: str, dest_key: str) -> str:
    """
    Upload a finished output video to the configured storage backend (R2 in
    production, local ``FileSystemStorage`` in dev) and return the public URL.

    The local file is *not* deleted here — callers are responsible for cleanup
    after they have persisted the returned URL.
    """
    from django.core.files.storage import default_storage

    with open(local_path, "rb") as f:
        saved_key = default_storage.save(dest_key, f)
    return default_storage.url(saved_key)
