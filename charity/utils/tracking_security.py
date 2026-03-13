from __future__ import annotations

from django.core import signing

TRACKING_TOKEN_SALT = "charity.tracking"


def build_tracking_token(*, tracking_id: int) -> str:
    return signing.dumps({"tracking_id": tracking_id}, salt=TRACKING_TOKEN_SALT, compress=True)


def resolve_tracking_token(token: str | None) -> int | None:
    if not token:
        return None

    try:
        payload = signing.loads(token, salt=TRACKING_TOKEN_SALT)
    except signing.BadSignature:
        return None

    tracking_id = payload.get("tracking_id")
    return tracking_id if isinstance(tracking_id, int) else None
