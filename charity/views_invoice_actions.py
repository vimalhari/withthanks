"""
Invoice action views — status transitions and outbound email/Stripe sends.

Extracted from views_invoices.py to keep that module focused on CRUD.
"""

import logging
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .models import Invoice
from .utils import resend_utils
from .utils.access_control import get_active_charity

logger = logging.getLogger(__name__)


def _get_invoice_for_request(request, invoice_id) -> Invoice:
    """Return the Invoice ensuring the user has access to it."""
    charity = get_active_charity(request)
    if request.user.is_superuser and not charity:
        return get_object_or_404(Invoice, id=invoice_id)
    return get_object_or_404(Invoice, id=invoice_id, charity=charity)


@login_required(login_url="charity_login")
def invoice_mark_paid(request, invoice_id):
    if request.method == "POST":
        invoice = _get_invoice_for_request(request, invoice_id)
        invoice.status = "Paid"
        invoice.save()
        messages.success(request, f"Invoice {invoice.invoice_number} marked as paid.")
    return redirect("invoice_detail", invoice_id=invoice_id)


@login_required(login_url="charity_login")
def invoice_void(request, invoice_id):
    if request.method == "POST":
        invoice = _get_invoice_for_request(request, invoice_id)

        from .services.stripe_service import is_enabled as stripe_enabled
        from .services.stripe_service import void_stripe_invoice

        if stripe_enabled() and invoice.stripe_invoice_id:
            void_stripe_invoice(invoice)

        invoice.status = "Void"
        invoice.save()
        messages.success(request, f"Invoice {invoice.invoice_number} has been voided.")
    return redirect("invoice_detail", invoice_id=invoice_id)


def _generate_invoice_pdf_bytes(invoice: Invoice) -> bytes:
    """Render invoice HTML to PDF and return the raw PDF bytes."""
    import os

    from django.conf import settings

    logo_path = os.path.join(
        settings.BASE_DIR, "charity", "static", "charity", "img", "with_thanks_logo_header.png"
    )
    html = render_to_string(
        "_invoice_content.html", {"invoice": invoice, "logo_path": logo_path, "is_pdf": True}
    )
    buffer = BytesIO()
    pisa.CreatePDF(html, dest=buffer)
    return buffer.getvalue()


@login_required(login_url="charity_login")
def invoice_send_email(request, invoice_id):
    invoice = _get_invoice_for_request(request, invoice_id)

    try:
        recipient = invoice.billing_email
        if not recipient:
            messages.error(request, "Invoice has no billing email address.")
            return redirect("invoice_detail", invoice_id=invoice.id)

        pdf_bytes = _generate_invoice_pdf_bytes(invoice)
        resend_utils.send_invoice_email(
            to_email=recipient,
            invoice_pdf_bytes=pdf_bytes,
            invoice_number=invoice.invoice_number,
            subject=f"Invoice {invoice.invoice_number} from {invoice.charity.client_name}",
            from_email=None,
            filename=f"Invoice_{invoice.invoice_number}.pdf",
        )
        if invoice.status == "Draft":
            invoice.status = "Sent"
            invoice.save()
        messages.success(request, f"Invoice sent to {recipient} successfully.")
    except Exception as exc:
        logger.error("Failed to send invoice email: %s", exc)
        messages.error(request, f"Failed to send email: {exc}")

    return redirect("invoice_detail", invoice_id=invoice.id)


@login_required(login_url="charity_login")
def invoice_stripe_send(request, invoice_id):
    """Create and send an invoice via Stripe."""
    from .services.stripe_service import (
        finalize_and_send_invoice,
    )
    from .services.stripe_service import (
        is_enabled as stripe_enabled,
    )

    if not stripe_enabled():
        messages.error(request, "Stripe is not configured. Set STRIPE_SECRET_KEY in your .env.")
        return redirect("invoice_detail", invoice_id=invoice_id)

    invoice = _get_invoice_for_request(request, invoice_id)

    if request.method == "POST":
        try:
            hosted_url = finalize_and_send_invoice(invoice)
            messages.success(
                request,
                f"Invoice {invoice.invoice_number} sent via Stripe. "
                f'<a href="{hosted_url}" target="_blank">View payment page</a>',
            )
        except Exception as exc:
            logger.error("Stripe send failed for invoice %s: %s", invoice.invoice_number, exc)
            messages.error(request, f"Failed to send via Stripe: {exc}")

    return redirect("invoice_detail", invoice_id=invoice_id)
