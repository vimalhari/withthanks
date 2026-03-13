"""
Invoice export views — PDF, CSV, and JSON renderings.

Extracted from views_invoices.py to keep that module focused on CRUD.
"""

import logging
import os
from io import BytesIO

import defusedcsv
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from .models import Invoice
from .utils.access_control import get_active_charity
from .views_invoice_actions import _get_invoice_for_request

logger = logging.getLogger(__name__)


def _render_invoice_to_pdf(invoice: Invoice) -> bytes:
    """Render the invoice template to PDF bytes using xhtml2pdf."""
    logo_path = os.path.join(
        settings.BASE_DIR, "charity", "static", "charity", "img", "with_thanks_logo_header.png"
    )
    html = render_to_string(
        "_invoice_content.html", {"invoice": invoice, "logo_path": logo_path, "is_pdf": True}
    )
    pdf_html = (
        "<!DOCTYPE html><html><head><style>"
        "@page {size: A4; margin: 15mm;} "
        "body {font-family: 'Helvetica'; font-size: 10px;}"
        "</style></head><body>"
        f"{html}</body></html>"
    )
    buffer = BytesIO()
    pisa.CreatePDF(pdf_html, dest=buffer)
    buffer.seek(0)
    return buffer.getvalue()


@login_required(login_url="charity_login")
def invoice_export_pdf(request, invoice_id):
    invoice = _get_invoice_for_request(request, invoice_id)
    charity = get_active_charity(request)
    if not request.user.is_superuser and invoice.charity != charity:
        return redirect("invoices")

    pdf_bytes = _render_invoice_to_pdf(invoice)
    if not pdf_bytes:
        return HttpResponse("Error generating PDF", status=500)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="invoice_{invoice.invoice_number}.pdf"'
    return response


@login_required(login_url="charity_login")
def invoice_export_csv(request, invoice_id):
    invoice = _get_invoice_for_request(request, invoice_id)
    charity = get_active_charity(request)
    if not request.user.is_superuser and invoice.charity != charity:
        return redirect("invoices")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="invoice_{invoice.invoice_number}.csv"'
    writer = defusedcsv.writer(response)
    writer.writerow(["Invoice Number", "Charity", "Issue Date", "Due Date", "Status", "Amount"])
    writer.writerow(
        [
            invoice.invoice_number,
            invoice.charity.charity_name,
            invoice.issue_date,
            invoice.due_date,
            invoice.status,
            invoice.amount,
        ]
    )
    return response


@login_required(login_url="charity_login")
def invoice_export_json(request, invoice_id):
    invoice = _get_invoice_for_request(request, invoice_id)
    charity = get_active_charity(request)
    if not request.user.is_superuser and invoice.charity != charity:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    return JsonResponse(
        {
            "invoice_number": invoice.invoice_number,
            "charity": invoice.charity.charity_name,
            "issue_date": str(invoice.issue_date),
            "due_date": str(invoice.due_date),
            "status": invoice.status,
            "amount": float(invoice.amount),
        }
    )
