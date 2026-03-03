"""
Custom exceptions for the WithThanks Celery task pipeline.

Differentiating between fatal and transient errors lets each task decide
whether retrying makes sense without ever re-running expensive video
generation steps.
"""


class FatalTaskError(Exception):
    """
    Unrecoverable error — the task should fail immediately without a retry.

    Examples:
      - Required base video file does not exist on disk or in R2
      - Campaign configuration is fundamentally invalid
    """


class TransientTaskError(Exception):
    """
    Recoverable error — the task should be retried after a back-off delay.

    Examples:
      - Resend API rate limit (429)
      - Cloudflare Stream upload timeout
      - Temporary network failure
    """
