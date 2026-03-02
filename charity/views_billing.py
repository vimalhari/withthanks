from django.http import JsonResponse
from django.views import View
from django.shortcuts import get_object_or_404, render
from .models import InvoiceService, Invoice, InvoiceLineItem, Charity
from .utils.access_control import get_active_charity
from django.utils.decorators import method_decorator
import json
from decimal import Decimal

class ServiceCatalogAPI(View):
    """
    CRUD API for global services available to all clients.
    """
    def get(self, request):
        services = InvoiceService.objects.all().order_by('category', 'name')
        data = [
            {
                'id': s.id,
                'name': s.name,
                'category': s.get_category_display(),
                'category_raw': s.category,
                'unit_price': float(s.unit_price),
                'description': s.description,
                'active': s.is_active
            } for s in services
        ]
        return JsonResponse({'services': data})

    def post(self, request):
        if not request.user.is_superuser:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        try:
            data = json.loads(request.body)
            service = InvoiceService.objects.create(
                name=data.get('name'),
                category=data.get('category'),
                unit_price=Decimal(str(data.get('unit_price', 0))),
                description=data.get('description', ''),
                is_active=data.get('active', True)
            )
            return JsonResponse({'success': True, 'id': service.id})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    def put(self, request, service_id=None):
        if not request.user.is_superuser:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        if not service_id:
            return JsonResponse({'error': 'Service ID required'}, status=400)
            
        service = get_object_or_404(InvoiceService, id=service_id)
        try:
            data = json.loads(request.body)
            service.name = data.get('name', service.name)
            service.category = data.get('category', service.category)
            service.unit_price = Decimal(str(data.get('unit_price', service.unit_price)))
            service.description = data.get('description', service.description)
            service.is_active = data.get('active', service.is_active)
            service.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    def delete(self, request, service_id=None):
        if not request.user.is_superuser:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
            
        if not service_id:
            return JsonResponse({'error': 'Service ID required'}, status=400)
            
        service = get_object_or_404(InvoiceService, id=service_id)
        service.delete()
        return JsonResponse({'success': True})

class InvoiceCalculationAPI(View):
    """
    Calculates subtotal, tax, and total based on provided items before saving.
    """
    def post(self, request):
        try:
            data = json.loads(request.body)
            items = data.get('items', [])
            discount_percent = Decimal(str(data.get('discount_percent', 0)))
            tax_percent = Decimal(str(data.get('tax_percent', 20)))
            
            subtotal = Decimal('0.00')
            for item in items:
                qty = Decimal(str(item.get('quantity', 1)))
                price = Decimal(str(item.get('unit_price', 0)))
                subtotal += qty * price
            
            discount_amount = (subtotal * discount_percent) / 100
            taxable_amount = subtotal - discount_amount
            tax_amount = (taxable_amount * tax_percent) / 100
            total = taxable_amount + tax_amount
            
            return JsonResponse({
                'subtotal': float(subtotal),
                'discount_amount': float(discount_amount),
                'tax_amount': float(tax_amount),
                'total': float(total)
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

class CreateInvoiceAPI(View):
    """
    Handles invoice creation with line items via JSON.
    """
    def post(self, request):
        try:
            data = json.loads(request.body)
            charity_id = data.get('charity_id')
            charity = get_object_or_404(Charity, id=charity_id)
            
            from django.utils import timezone
            from datetime import timedelta
            
            # Create the invoice
            invoice = Invoice.objects.create(
                charity=charity,
                invoice_number="", # Will be auto-generated if logic exists or we generate now
                amount=0, # Will be calculated
                issue_date=timezone.now().date(),
                due_date=timezone.now().date() + timedelta(days=30),
                status='Draft',
                discount_percent=Decimal(str(data.get('discount_percent', 0))),
                tax_percent=Decimal(str(data.get('tax_percent', 20))),
            )
            
            invoice.generate_invoice_number()
            
            # Add items
            for item_data in data.get('items', []):
                service_id = item_data.get('service_id')
                service = None
                if service_id:
                    service = InvoiceService.objects.get(id=service_id)
                
                qty = Decimal(str(item_data.get('quantity', 1)))
                price = Decimal(str(item_data.get('unit_price', 0)))
                line_total = qty * price
                
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    service=service,
                    description=item_data.get('description', service.name if service else 'Manual Entry'),
                    quantity=qty,
                    unit_price=price,
                    total_amount=line_total
                )
            
            # Final calculation
            invoice.calculate_totals()
            
            return JsonResponse({
                'success': True, 
                'invoice_id': str(invoice.id),
                'invoice_number': invoice.invoice_number
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

def services_management_view(request):
    """
    Dedicated view to host the React-based Service Management UI.
    """
    return render(request, 'charity/services_management.html')
