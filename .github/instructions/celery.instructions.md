---
description: Celery task and background job conventions for WithThanks
applyTo: "charity/tasks.py,charity/services/**/*.py"
---

# Celery Tasks & Services Instructions

## Task Declaration
- Always use `@shared_task(bind=True)` decorator.
- Set explicit `queue` parameter matching `CELERY_TASK_ROUTES` in settings:
  ```python
  @shared_task(bind=True, queue="video")
  def process_donation_row(self, job_id):
      ...
  ```

## Queue Architecture
| Queue | Purpose | Examples |
|---|---|---|
| `video` | CPU/IO-heavy processing | TTS generation, FFmpeg, email send |
| `default` | Lightweight orchestration | `batch_process_csv`, callbacks |
| `maintenance` | Periodic beat tasks | Stats refresh, invoice overdue, cleanup |

## Task Routing
- Add new tasks to `CELERY_TASK_ROUTES` in `withthanks/settings.py`.
- Pattern: `"charity.tasks.<task_name>": {"queue": "<queue_name>"}`.

## Workflow Patterns
- Use Celery primitives for multi-step workflows:
  - `chain(task1.s(), task2.s())` — sequential pipeline
  - `group(task1.s(), task2.s())` — parallel execution
  - `chord(group(...), callback.s())` — parallel with final callback
- The video pipeline uses a 3-stage chain: Validate → Process → Deliver.

## Error Handling
- Import and raise `FatalTaskError` from `charity.exceptions` for unrecoverable errors.
- Use `try/except` with logging for recoverable errors.
- Set `self.update_state(state="FAILURE", meta={"error": str(e)})` before raising.
- Clean up intermediate files in `finally` blocks.

## Services (`charity/services/`)
- Business logic lives in service modules, NOT in tasks or views.
- Services are plain Python modules (composition over inheritance).
- Available services:
  - `video_build_service.py` — FFmpeg video composition
  - `video_pipeline_service.py` — Cloudflare Stream upload, URL resolution
  - `video_dispatch_service.py` — orchestration of video processing
  - `invoice_service.py` — invoice generation and management
  - `batch_service.py` — batch processing logic
  - `cleanup_service.py` — file and data cleanup
  - `analytics_service.py` — analytics aggregation
  - `sync_bridge.py` — async-to-sync bridge utilities

## Utility Modules (`charity/utils/`)
- `access_control.py` — `get_active_charity()` and permissions helpers
- `cloudflare_stream.py` — Cloudflare Stream API client
- `resend_utils.py` — Resend email API wrapper
- `media_utils.py` — file path generation for uploads
- `voiceover_utils.py` — ElevenLabs TTS generation
- `video_utils.py` — FFmpeg helper functions
- `exports.py` — CSV/Excel export utilities
- `filenames.py` — safe filename generation

## Periodic Tasks
- Configured via `django-celery-beat` with `DatabaseScheduler`.
- Manage in Django admin or via `PeriodicTask` model.
- All periodic tasks route to `maintenance` queue.

## Performance
- Use `DonationJob.objects.select_related("charity", "campaign", "donation_batch")` when loading jobs in tasks.
- Clean up temporary files after processing (use `cleanup_intermediate()` helper).
- Respect `CELERY_TASK_TIME_LIMIT` (30 min) and `CELERY_TASK_SOFT_TIME_LIMIT` (25 min).
