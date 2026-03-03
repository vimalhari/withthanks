"""
Invoice business logic.

Centralises operations that were previously scattered across model methods,
Celery tasks, and views.  All public functions accept and return plain Python
objects so they can be unit-tested without a running Celery worker.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from charity.models import Invoice

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Invoice number generation
# ---------------------------------------------------------------------------


def generate_invoice_number() -> str:
    """
    Auto-generate the next available invoice number for the current year.

    Format: ``INV-YYYY-NNNN`` (e.g. ``INV-2026-0042``).

    Looks at all existing invoice numbers for the current year and returns
    the next sequence number, padded to 4 digits.
    """
    from charity.models import Invoice

    year = datetime.now().year
    prefix = f"INV-{year}-"

    last = (
        Invoice.objects.filter(invoice_number__startswith=prefix)
        .order_by("-invoice_number")
        .first()
    )
    seq = (int(last.invoice_number.rsplit("-", 1)[-1]) + 1) if last else 1
    return f"{prefix}{seq:04d}"


# ---------------------------------------------------------------------------
# Invoice totals calculation
# ---------------------------------------------------------------------------


def calculate_invoice_totals(invoice: Invoice) -> None:
    """
    Recalculate *invoice* totals from its line items and persist.

    Updates ``subtotal``, ``discount_amount``, ``tax_amount``, and
    ``amount`` then calls ``invoice.save()``.
    """
    from django.db.models import Sum

    subtotal = invoice.line_items.aggregate(sum=Sum("total_amount"))["sum"] or 0
    invoice.subtotal = subtotal

    invoice.discount_amount = (
        (invoice.subtotal * invoice.discount_percent) / 100 if invoice.discount_percent > 0 else 0
    )
    taxable = invoice.subtotal - invoice.discount_amount
    invoice.tax_amount = (taxable * invoice.tax_percent) / 100 if invoice.tax_percent > 0 else 0
    invoice.amount = taxable + invoice.tax_amount
    invoice.save()


# ---------------------------------------------------------------------------
# Bulk status transitions
# ---------------------------------------------------------------------------


def mark_overdue_bulk() -> dict[str, int]:
    """
    Transition every ``Sent`` invoice whose ``due_date`` is in the past to
    ``Overdue`` status.

    Called by the ``mark_overdue_invoices`` Celery beat task.

    Returns a dict with the count of invoices updated.
    """
    from django.utils.timezone import now

    from charity.models import Invoice

    updated = Invoice.objects.filter(
        status="Sent",
        due_date__lt=now().date(),
    ).update(status="Overdue")

    logger.info("Marked %d invoices as Overdue", updated)
    return {"marked_overdue": updated}
