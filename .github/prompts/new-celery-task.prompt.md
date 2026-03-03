---
description: "Generate a new Celery task with proper queue routing and error handling"
---

# New Celery Task

Create a Celery task following WithThanks conventions.

## Requirements
- Use `@shared_task(bind=True)` decorator.
- Place in `charity/tasks.py`.
- Add queue routing in `CELERY_TASK_ROUTES` in `withthanks/settings.py`.
- Handle errors with try/except, log failures, and use `FatalTaskError` for unrecoverable issues.
- Clean up temporary files in `finally` blocks.
- Use `select_related`/`prefetch_related` when loading model instances.

## Template
```python
@shared_task(bind=True)
def ${1:task_name}(self, ${2:params}):
    """${3:Description of what this task does}."""
    logger.info("Starting ${1} with %s", ${2})

    try:
        # Load data with optimized queries
        # obj = Model.objects.select_related("charity").get(id=obj_id)

        # Business logic here (delegate to services)
        # result = some_service.do_work(obj)

        logger.info("${1} completed successfully for %s", ${2})
        return {"status": "success"}

    except FatalTaskError:
        logger.error("Fatal error in ${1} for %s", ${2}, exc_info=True)
        raise

    except Exception as exc:
        logger.error("${1} failed for %s: %s", ${2}, exc, exc_info=True)
        raise self.retry(exc=exc, countdown=60, max_retries=3)
```

## Queue Selection Guide
| Queue | Use When |
|---|---|
| `video` | CPU/IO-heavy (FFmpeg, TTS, email send) |
| `default` | Lightweight orchestration, callbacks |
| `maintenance` | Periodic cleanup, stats refresh |

## After Creating
1. Add route in `withthanks/settings.py` → `CELERY_TASK_ROUTES`:
   ```python
   "charity.tasks.${1}": {"queue": "${4:queue_name}"},
   ```
2. For periodic tasks, configure schedule in Django admin (django-celery-beat).
