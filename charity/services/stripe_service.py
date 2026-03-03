"""
Stripe integration service for WithThanks invoice billing.

This module provides helpers for:
  - Creating Stripe Customers from Charity records
  - Creating Stripe Invoices from WithThanks Invoice records
  - Sending Stripe invoices (hosted payment page)
  - Handling Stripe webhook events (invoice.paid, invoice.payment_failed)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from charity.models import Charity, Invoice

logger = logging.getLogger(__name__)

_stripe = None


def _get_stripe():
    """Lazy-load stripe module and configure API key."""
    global _stripe
    if _stripe is None:
        import stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        _stripe = stripe
    return _stripe


def is_enabled() -> bool:
    return bool(getattr(settings, "STRIPE_ENABLED", False))


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------


def get_or_create_customer(charity: Charity) -> str:
    """
    Ensure the Charity has a Stripe Customer ID.
    Creates one if it doesn't exist, then persists it on the Charity model.
    Returns the Stripe Customer ID.
    """
    if charity.stripe_customer_id:
        return charity.stripe_customer_id

    stripe = _get_stripe()
    customer = stripe.Customer.create(
        name=charity.organization_name,
        email=charity.billing_email or charity.contact_email,
        metadata={"charity_id": str(charity.id), "source": "withthanks"},
    )

    charity.stripe_customer_id = customer.id
    charity.save(update_fields=["stripe_customer_id"])
    logger.info(f"Created Stripe Customer {customer.id} for Charity {charity.id}")
    return customer.id


# ---------------------------------------------------------------------------
# Invoice management
# ---------------------------------------------------------------------------


def create_stripe_invoice(invoice: Invoice) -> str:
    """
    Create a Stripe Invoice from a WithThanks Invoice.
    Adds line items matching the InvoiceLineItem records.
    Returns the Stripe Invoice ID.
    """
    stripe = _get_stripe()
    customer_id = get_or_create_customer(invoice.charity)

    # Create the Stripe invoice
    stripe_invoice = stripe.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=max((invoice.due_date - invoice.issue_date).days, 1),
        metadata={
            "withthanks_invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
        },
        auto_advance=False,  # Don't auto-finalize — we control when to send
    )

    # Add line items
    for item in invoice.line_items.all():
        stripe.InvoiceItem.create(
            customer=customer_id,
            invoice=stripe_invoice.id,
            description=item.description,
            quantity=int(item.quantity),
            unit_amount=int(item.unit_price * 100),  # Stripe uses cents
            currency="gbp",
        )

    # Add tax if applicable
    if invoice.tax_amount and invoice.tax_amount > 0:
        stripe.InvoiceItem.create(
            customer=customer_id,
            invoice=stripe_invoice.id,
            description=f"VAT ({invoice.tax_percent}%)",
            quantity=1,
            unit_amount=int(invoice.tax_amount * 100),
            currency="gbp",
        )

    # Save the Stripe invoice ID on our model
    invoice.stripe_invoice_id = stripe_invoice.id
    invoice.save(update_fields=["stripe_invoice_id"])

    logger.info(f"Created Stripe Invoice {stripe_invoice.id} for Invoice {invoice.invoice_number}")
    return stripe_invoice.id


def finalize_and_send_invoice(invoice: Invoice) -> str:
    """
    Finalize and send a Stripe Invoice.
    The donor/charity receives an email with a hosted payment page link.
    Returns the hosted invoice URL.
    """
    stripe = _get_stripe()

    if not invoice.stripe_invoice_id:
        create_stripe_invoice(invoice)

    # Finalize the invoice (locks line items)
    stripe_invoice = stripe.Invoice.finalize_invoice(invoice.stripe_invoice_id)

    # Send the invoice email
    stripe.Invoice.send_invoice(invoice.stripe_invoice_id)

    # Update our model
    invoice.stripe_hosted_url = stripe_invoice.hosted_invoice_url or ""
    invoice.stripe_pdf_url = stripe_invoice.invoice_pdf or ""
    if invoice.status == "Draft":
        invoice.status = "Sent"
    invoice.save(update_fields=["stripe_hosted_url", "stripe_pdf_url", "status"])

    logger.info(f"Sent Stripe Invoice {invoice.stripe_invoice_id} for {invoice.invoice_number}")
    return invoice.stripe_hosted_url


def void_stripe_invoice(invoice: Invoice) -> bool:
    """Void a Stripe invoice. Returns True on success."""
    if not invoice.stripe_invoice_id:
        return True

    stripe = _get_stripe()
    try:
        stripe.Invoice.void_invoice(invoice.stripe_invoice_id)
        logger.info(f"Voided Stripe Invoice {invoice.stripe_invoice_id}")
        return True
    except Exception as exc:
        logger.error(f"Failed to void Stripe Invoice {invoice.stripe_invoice_id}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------


def handle_webhook_event(payload: bytes, sig_header: str) -> dict:
    """
    Verify and process a Stripe webhook event.
    Returns a dict with the event type and processing result.
    """
    stripe = _get_stripe()

    event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)

    event_type = event["type"]
    data_object = event["data"]["object"]

    handler = _WEBHOOK_HANDLERS.get(event_type)
    if handler:
        handler(data_object)
        return {"event_type": event_type, "status": "processed"}

    logger.debug(f"Unhandled Stripe event type: {event_type}")
    return {"event_type": event_type, "status": "ignored"}


def _handle_invoice_paid(stripe_invoice: dict):
    """Mark our Invoice as Paid when Stripe confirms payment."""
    from charity.models import Invoice

    wt_invoice_id = (stripe_invoice.get("metadata") or {}).get("withthanks_invoice_id")
    if not wt_invoice_id:
        logger.warning("invoice.paid event has no withthanks_invoice_id metadata")
        return

    try:
        invoice = Invoice.objects.get(id=wt_invoice_id)
        invoice.status = "Paid"
        invoice.stripe_payment_intent_id = stripe_invoice.get("payment_intent", "")
        invoice.save(update_fields=["status", "stripe_payment_intent_id"])
        logger.info(f"Invoice {invoice.invoice_number} marked as Paid via Stripe webhook")
    except Invoice.DoesNotExist:
        logger.error(f"Invoice {wt_invoice_id} not found for Stripe payment")


def _handle_invoice_payment_failed(stripe_invoice: dict):
    """Log payment failure — invoice stays in Sent/Overdue status."""
    wt_invoice_id = (stripe_invoice.get("metadata") or {}).get("withthanks_invoice_id")
    if wt_invoice_id:
        logger.warning(
            f"Stripe payment failed for Invoice {wt_invoice_id}: "
            f"{stripe_invoice.get('last_finalization_error', {}).get('message', 'unknown error')}"
        )


def _handle_invoice_finalized(stripe_invoice: dict):
    """Update hosted URL and PDF URL when invoice is finalized."""
    from charity.models import Invoice

    wt_invoice_id = (stripe_invoice.get("metadata") or {}).get("withthanks_invoice_id")
    if not wt_invoice_id:
        return

    try:
        invoice = Invoice.objects.get(id=wt_invoice_id)
        invoice.stripe_hosted_url = stripe_invoice.get("hosted_invoice_url", "")
        invoice.stripe_pdf_url = stripe_invoice.get("invoice_pdf", "")
        invoice.save(update_fields=["stripe_hosted_url", "stripe_pdf_url"])
    except Invoice.DoesNotExist:
        pass


_WEBHOOK_HANDLERS = {
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "invoice.finalized": _handle_invoice_finalized,
}
