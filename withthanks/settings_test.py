from __future__ import annotations

from .settings import *  # noqa: F401, F403

# Use plain staticfiles storage during tests — no manifest required.
# This avoids `ValueError: Missing staticfiles manifest entry for ...`
# when collectstatic / Tailwind build has not been run in CI.
STORAGES["staticfiles"] = {  # type: ignore[name-defined]  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
