import os
import tempfile
import uuid

from django.utils.text import slugify


def get_client_media_path(instance, filename):
    """
    Generates a client-isolated file path for media uploads.
    Format: clients/client_{id}/{category}/{filename}

    Handles:
    - Charity (logo, thank_you_card)
    - Campaign (video_template_override)
    """
    client_id = "unknown"
    category = "misc"

    # Check model type and extract client_id
    model_name = instance._meta.model_name

    if model_name == "charity":
        # If the charity is being created and has no ID yet,
        # we might have an issue. Best practice: save first, then upload.
        # However, if it happens, we'll use 'pending' or try to rely on
        # pre-save logic (rare for Logo on create).
        client_id = str(instance.pk) if instance.pk else "pending_save"

        # Determine category based on field?
        # Since upload_to passes the instance, we can't easily know WHICH field
        # triggered this if we use the same function for both.
        # But we can define partials or infer from filename/extension context if strictness needed.
        # For simplicity, we'll put all charity branding in 'branding'
        category = "branding"

    elif model_name == "campaign":
        if hasattr(instance, "client_id") and instance.client_id:
            client_id = str(instance.client_id)
        elif hasattr(instance, "client") and instance.client:
            client_id = str(instance.client.pk)

        category = "campaign_overrides"

    # Sanitize filename
    name, ext = os.path.splitext(filename)
    safe_name = slugify(name)
    # Add UUID to filename to prevent overwrites/caching issues
    final_filename = f"{safe_name}_{uuid.uuid4().hex[:8]}{ext}"

    return f"clients/client_{client_id}/{category}/{final_filename}"


def extract_blob_to_temp(blob_data, suffix=".mp4"):
    """
    Extracts binary blob data to a temporary file.
    Returns the path to the temp file.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(blob_data)
        return tmp.name
