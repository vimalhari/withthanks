from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from .models import Charity, Invoice, InvoiceLineItem, InvoiceService


class InvoiceCalculationAPI(LoginRequiredMixin, View):
    """
    Calculates subtotal, tax, and total based on provided items before saving.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
            items = data.get("items", [])
            tax_percent = Decimal(str(data.get("tax_percent", 20)))

            subtotal = Decimal("0.00")
            for item in items:
                qty = Decimal(str(item.get("quantity", 1)))
                price = Decimal(str(item.get("unit_price", 0)))
                subtotal += qty * price

            tax_amount = (subtotal * tax_percent) / 100
            total = subtotal + tax_amount

            return JsonResponse(
                {
                    "subtotal": float(subtotal),
                    "discount_amount": 0,
                    "tax_amount": float(tax_amount),
                    "total": float(total),
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


class CreateInvoiceAPI(LoginRequiredMixin, View):
    """
    Handles invoice creation with line items via JSON.
    """

    def post(self, request):
        try:
            data = json.loads(request.body)
            charity_id = data.get("charity_id")
            charity = get_object_or_404(Charity, id=charity_id)

            from datetime import timedelta

            from django.utils import timezone

            # Create the invoice
            invoice = Invoice.objects.create(
                charity=charity,
                invoice_number="",  # Will be auto-generated if logic exists or we generate now
                amount=0,  # Will be calculated
                issue_date=timezone.now().date(),
                due_date=timezone.now().date() + timedelta(days=30),
                status="Draft",
                discount_percent=0,
                tax_percent=Decimal(str(data.get("tax_percent", 20))),
                # Pre-fill billing contact from the charity
                billing_email=charity.billing_email or charity.contact_email or "",
                additional_billing_emails=charity.additional_billing_emails or "",
            )

            invoice.generate_invoice_number()

            # Add items
            for item_data in data.get("items", []):
                service_id = item_data.get("service_id")
                service = None
                if service_id:
                    service = InvoiceService.objects.get(id=service_id)

                qty = Decimal(str(item_data.get("quantity", 1)))
                price = Decimal(str(item_data.get("unit_price", 0)))
                line_total = qty * price

                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    service=service,
                    description=item_data.get(
                        "description", service.name if service else "Manual Entry"
                    ),
                    quantity=qty,
                    unit_price=price,
                    total_amount=line_total,
                )

            # Final calculation
            invoice.calculate_totals()

            return JsonResponse(
                {
                    "success": True,
                    "invoice_id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
