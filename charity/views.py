# charity/views.py
import csv
import logging
import traceback
from pathlib import Path
from django.shortcuts import render
from django.conf import settings
from .forms import CSVUploadForm
from .utils.voiceover import generate_voiceover
from .utils.video_utils import stitch_voice_and_overlay
from .utils.resend_utils import send_video_email
from .utils.filenames import safe_filename

logger = logging.getLogger(__name__)

def upload_csv_and_process(request):
    """
    Handle CSV upload, generate personalized first 5s of video with TTS and overlay,
    append remaining base video, and send via email.
    """
    message = None
    visible_errors = []  # 👈 store short messages for display

    if request.method == "POST":
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES["csv_file"]

            try:
                lines = csv_file.read().decode("utf-8").splitlines()
            except Exception as e:
                message = "Uploaded file must be a UTF-8 encoded CSV."
                logger.exception("CSV decode failed: %s", e)
                return render(request, "upload_csv.html", {"form": form, "message": message})

            reader = csv.DictReader(lines)
            processed_count = 0
            errors = []

            for i, row in enumerate(reader, start=1):
                try:
                    name = (row.get("name") or "donor").strip()
                    amount = (row.get("amount") or "").strip()
                    email = (row.get("email") or "").strip()

                    if not email:
                        logger.info("Row %d skipped: no email", i)
                        continue

                    # Sanitize file name
                    file_base = safe_filename(f"{name}_{amount}")[:120]

                    # Step 1: generate TTS voiceover
                    voiceover_path = generate_voiceover(
                        text=f"Hi {name}, thank you for your donation of {amount} euros! We really appreciate your support.",
                        file_name=file_base,
                    )

                    # Step 2: stitch first 5s intro with TTS + overlay, then append remaining video
                    stitched_video_path = stitch_voice_and_overlay(
                        input_video=settings.BASE_VIDEO_PATH,
                        tts_wav=voiceover_path,
                        overlay_text=f"Hi {name}, thank you for your donation of {amount} euros! We really appreciate your support.",
                        out_filename=f"{file_base}.mp4",
                        output_dir=settings.VIDEO_OUTPUT_DIR,
                        intro_duration=5
                    )

                    # Step 3: send video to donor via email
                    send_video_email(email, stitched_video_path)
                    processed_count += 1

                except Exception as exc:
                    logger.error("Row %d failed: %s\n%s", i, exc, traceback.format_exc())
                    errors.append({"row": i, "error": str(exc)})
                    # 👇 add short visible message for web display
                    visible_errors.append(f"Row {i}: {exc}")

            message = f"Processed {processed_count} donations successfully!"
            if errors:
                message += f" ({len(errors)} rows failed.)"

    else:
        form = CSVUploadForm()

    # 👇 Pass visible_errors to the template
    return render(request, "upload_csv.html", {"form": form, "message": message, "errors": visible_errors})
