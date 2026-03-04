from __future__ import annotations

"""
Blackbaud Raiser's Edge NXT adapter.

Implements read-only donation sync via the Blackbaud SKY API:
  - OAuth 2.0 token refresh (client_credentials / refresh_token grant)
  - Gift list endpoint: GET /gift/v1/gifts
  - Constituent endpoint: GET /constituent/v1/constituents/{id}

Docs: https://developer.sky.blackbaud.com/docs/services/58bdd6d1d7dcde0508674123
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, TYPE_CHECKING

import requests
from django.conf import settings
from django.utils import timezone as dj_timezone

from charity.utils.crm_adapters.base import CRMAdapter, CRMError

if TYPE_CHECKING:
    from charity.models import Charity

logger = logging.getLogger(__name__)

_SKY_BASE = "https://api.sky.blackbaud.com"
_TOKEN_URL = "https://oauth2.sky.blackbaud.com/token"

# Blackbaud gift types that represent actual monetary donations
_GIFT_TYPES = ("Donation", "MonthlyGiving", "Pledge", "PledgePayment")


class BlackbaudAdapter(CRMAdapter):
    """
    Blackbaud Raiser's Edge NXT read-only adapter.

    Token lifecycle is managed automatically: if the stored access token
    has expired (or is within 60 s of expiry) ``_ensure_token`` will
    perform a refresh before any API call is made.
    """

    def __init__(self, charity: "Charity") -> None:
        super().__init__(charity)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Bb-Api-Subscription-Key": settings.BLACKBAUD_SUBSCRIPTION_KEY,
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _token_expired(self) -> bool:
        """Return True if the current access token is missing or about to expire."""
        charity = self.charity
        if not charity.blackbaud_access_token:
            return True
        if not charity.blackbaud_token_expires_at:
            return True
        # Refresh if expiry is within 60 seconds
        margin_seconds = 60
        now_utc = dj_timezone.now()
        expires_at = charity.blackbaud_token_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return (expires_at - now_utc).total_seconds() < margin_seconds

    def _ensure_token(self) -> None:
        """Refresh the access token if it has expired, saving new tokens to Charity."""
        if not self._token_expired():
            return

        charity = self.charity
        if not charity.blackbaud_refresh_token:
            raise CRMError(
                f"Charity {charity.id} has no Blackbaud refresh token. "
                "Re-authorise via the CRM connect flow."
            )

        logger.info("Refreshing Blackbaud token for charity %s", charity.id)
        resp = requests.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": charity.blackbaud_refresh_token,
                "client_id": settings.BLACKBAUD_CLIENT_ID,
                "client_secret": settings.BLACKBAUD_CLIENT_SECRET,
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise CRMError(
                f"Token refresh failed for charity {charity.id}: "
                f"{resp.status_code} {resp.text[:200]}"
            )

        data = resp.json()
        _save_tokens(charity, data)

        # Update the in-memory session header
        self._session.headers["Authorization"] = f"Bearer {charity.blackbaud_access_token}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_new_donations(self, since: datetime) -> list[dict]:
        """
        Pull all gifts in this charity's Raiser's Edge environment added
        *after* ``since`` and return them as normalized dicts.

        Handles Blackbaud pagination (``next_link`` cursor).
        """
        self._ensure_token()
        self._session.headers["Authorization"] = (
            f"Bearer {self.charity.blackbaud_access_token}"
        )

        # Format datetime as ISO 8601 used by SKY API
        since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        url = f"{_SKY_BASE}/gift/v1/gifts"
        params: dict[str, Any] = {
            "date_added": since_iso,
            "limit": 500,
        }

        gifts: list[dict] = []
        while url:
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 401:
                # Token may have been invalidated server-side; attempt one refresh
                logger.warning("401 received mid-sync for charity %s — refreshing token", self.charity.id)
                self._ensure_token()
                self._session.headers["Authorization"] = (
                    f"Bearer {self.charity.blackbaud_access_token}"
                )
                resp = self._session.get(url, params=params, timeout=30)

            if resp.status_code != 200:
                raise CRMError(
                    f"Gift list failed for charity {self.charity.id}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )

            body = resp.json()
            gifts.extend(body.get("value", []))

            url = body.get("next_link")  # type: ignore[assignment]
            params = {}  # next_link already contains all query params

        logger.info(
            "Blackbaud: fetched %d gifts for charity %s since %s",
            len(gifts),
            self.charity.id,
            since_iso,
        )

        # Normalise gifts into pipeline-ready dicts
        results: list[dict] = []
        for gift in gifts:
            normalized = self._normalize_gift(gift)
            if normalized:
                results.append(normalized)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _normalize_gift(self, gift: dict) -> dict | None:
        """
        Convert a Blackbaud gift record to a DonationJob-compatible dict.

        Returns None if the gift should be skipped (e.g. non-donation type,
        missing constituent email, or zero amount).
        """
        gift_type = gift.get("type", "")
        if gift_type not in _GIFT_TYPES:
            return None

        raw_amount = gift.get("amount", {}).get("value") or 0
        try:
            amount = Decimal(str(raw_amount))
        except Exception:
            amount = Decimal("0")
        if amount <= 0:
            return None

        constituent_id = gift.get("constituent_id")
        if not constituent_id:
            return None

        # Fetch constituent to resolve name + email
        try:
            constituent = self._fetch_constituent(constituent_id)
        except CRMError as exc:
            logger.warning("Skipping gift %s — constituent fetch failed: %s", gift.get("id"), exc)
            return None

        email = constituent.get("email")
        if not email:
            return None

        donated_at_raw = gift.get("date", {}).get("d") or gift.get("date_added")
        donated_at: datetime | None = None
        if donated_at_raw:
            try:
                # SKY API returns "2024-01-15T00:00:00+00:00" or similar
                donated_at = datetime.fromisoformat(donated_at_raw)
                if donated_at.tzinfo is None:
                    donated_at = donated_at.replace(tzinfo=timezone.utc)
            except ValueError:
                donated_at = dj_timezone.now()
        else:
            donated_at = dj_timezone.now()

        return {
            "donor_name": constituent.get("name", email),
            "donor_email": email,
            "amount": amount,
            "donated_at": donated_at,
            "campaign_type": "WithThanks",
            "external_id": gift.get("id", ""),
        }

    def _fetch_constituent(self, constituent_id: str) -> dict:
        """
        Fetch a single constituent and extract their name and primary email.

        Returns a dict with ``name`` and ``email`` keys.
        Raises ``CRMError`` if the API call fails.
        """
        resp = self._session.get(
            f"{_SKY_BASE}/constituent/v1/constituents/{constituent_id}",
            timeout=30,
        )
        if resp.status_code != 200:
            raise CRMError(
                f"Constituent {constituent_id} fetch failed: "
                f"{resp.status_code} {resp.text[:100]}"
            )
        data = resp.json()

        # Preferred email: email.address at top level, then email_addresses list
        email: str = data.get("email", {}).get("address", "")
        if not email:
            for addr_rec in data.get("email_addresses", {}).get("value", []):
                if addr_rec.get("do_not_contact") is False or not addr_rec.get("do_not_contact"):
                    candidate = addr_rec.get("address", "")
                    if candidate:
                        email = candidate
                        break

        return {
            "name": data.get("name", ""),
            "email": email,
        }


# ---------------------------------------------------------------------------
# Token persistence helper
# ---------------------------------------------------------------------------


def _save_tokens(charity: "Charity", token_data: dict) -> None:
    """Persist OAuth tokens from a token endpoint response to the Charity model."""
    from django.utils.timezone import now
    from datetime import timedelta

    charity.blackbaud_access_token = token_data["access_token"]
    if "refresh_token" in token_data:
        charity.blackbaud_refresh_token = token_data["refresh_token"]
    expires_in = int(token_data.get("expires_in", 3600))
    charity.blackbaud_token_expires_at = now() + timedelta(seconds=expires_in)

    # Some token responses include the environment_id
    env_id = (
        token_data.get("environment_id")
        or token_data.get("environment_name")
    )
    if env_id and not charity.blackbaud_environment_id:
        charity.blackbaud_environment_id = env_id

    charity.save(
        update_fields=[
            "blackbaud_access_token",
            "blackbaud_refresh_token",
            "blackbaud_token_expires_at",
            "blackbaud_environment_id",
        ]
    )
    logger.debug("Saved refreshed Blackbaud tokens for charity %s", charity.id)
