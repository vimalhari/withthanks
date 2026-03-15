"""
Base CRM adapter interface.

All CRM adapters must subclass ``CRMAdapter`` and implement
``fetch_new_donations``.  Each call must return a list of normalized
donation dicts that match the fields expected by the DonationJob pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from charity.models import Charity


class CRMAdapter(ABC):
    """Abstract base class for CRM read-only donation adapters."""

    def __init__(self, charity: Charity) -> None:
        self.charity = charity

    @abstractmethod
    def fetch_new_donations(self, since: datetime) -> list[dict]:
        """
        Fetch donations recorded *after* ``since`` from the CRM.

        Each returned dict must contain at minimum:
            - donor_name  (str)
            - donor_email (str)
            - amount      (Decimal | float | str)
            - donated_at  (datetime, UTC-aware)

        Optional keys:
            - donor_title       (str)
            - donor_first_name  (str)
            - donor_last_name   (str)
            - campaign_type  ("WithThanks" | "VDM" | "Gratitude"; defaults to "WithThanks")
            - external_id    (str, the CRM's own gift ID — for logging/dedup)

        Raises ``CRMError`` for unrecoverable API failures.
        """
        ...


class CRMError(Exception):
    """Raised when a CRM adapter encounters an unrecoverable API error."""
