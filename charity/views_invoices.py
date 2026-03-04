import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import InvoiceForm, InvoiceStep1Form, InvoiceStep2Form
from .models import Campaign, Charity, DonationBatch, DonationJob, Invoice, InvoiceLineItem
from .utils.access_control import get_active_charity

logger = logging.getLogger(__name__)


@login_required(login_url="charity_login")
def invoices_view(request):
    """
    Enhanced invoices dashboard with summary cards, filters, and pagination.
    PERFORMANCE: Uses select_related and combined aggregations.
    """
    charity = get_active_charity(request)
    if not charity and not request.user.is_superuser:
        return redirect("dashboard")

    # Base queryset with optimization
    if not charity:
        if request.user.is_superuser:
            invoices = Invoice.objects.all().select_related("charity", "campaign")
        else:
            invoices = Invoice.objects.none()
    else:
        invoices = Invoice.objects.filter(charity=charity).select_related("charity", "campaign")

    # Apply filters
    client_filter = request.GET.get("client")
    status_filter = request.GET.get("status")
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    if client_filter and client_filter not in ["All Clients", ""]:
        if client_filter.isdigit():
            invoices = invoices.filter(charity__id=client_filter)
        else:
            invoices = invoices.filter(charity__client_name__icontains=client_filter)

    if status_filter and status_filter not in ["All Status", ""]:
        invoices = invoices.filter(status=status_filter)

    if start_date:
        invoices = invoices.filter(issue_date__gte=start_date)
    if end_date:
        invoices = invoices.filter(issue_date__lte=end_date)

    # PERFORMANCE: Combined Aggregation
    stats = invoices.aggregate(
        total_invoices=Count("id"),
        total_billed=Sum("amount"),
        paid_amount=Sum("amount", filter=Q(status="Paid")),
        outstanding=Sum("amount", filter=Q(status__in=["Sent", "Overdue", "Draft"])),
    )
    # Ensure values are not None
    stats = {k: v or 0 for k, v in stats.items()}

    # Pagination
    paginator = Paginator(invoices.order_by("-issue_date"), 25)
    page = request.GET.get("page")
    invoices_page = paginator.get_page(page)

    if request.user.is_superuser:
        clients = Charity.objects.all().order_by("client_name")
    else:
        clients = [charity] if charity else []

    return render(
        request,
        "invoices.html",
        {
            "invoices": invoices_page,
            "stats": stats,
            "clients": clients,
            "current_charity": charity,
        },
    )


def get_slab_price(volume: int, personalized: bool = True) -> "float | str":
    """Calculate base campaign price based on volume and personalization.

    Args:
        volume: Number of DonationJob records in the billing period.
        personalized: True for PERSONALIZED video mode, False for TEMPLATE.

    Returns:
        Price as a float, or the string ``"POA"`` when volume > 3000.
    """
    slabs = {
        "personalized": [(99, 110), (300, 265), (500, 375), (1000, 575), (3000, 1025)],
        "standard": [(99, 99), (300, 250), (500, 350), (1000, 550), (3000, 1000)],
    }
    tier_slabs = slabs["personalized" if personalized else "standard"]
    for limit, price in tier_slabs:
        if volume <= limit:
            return price
    return "POA"  # Price on Application for > 3000


@login_required(login_url="charity_login")
def create_invoice_view(request):
    """3-Step Invoice Creation Wizard"""
    charity = get_active_charity(request)
    if not charity and not request.user.is_superuser:
        messages.warning(request, "Please select a client context from the dashboard.")
        return redirect("dashboard")

    step = request.session.get("invoice_wizard_step", 1)
    wizard_data = request.session.get("invoice_wizard_data", {})

    wizard_charity_id = wizard_data.get("client_id") or (charity.id if charity else None)
    wizard_charity = (
        Charity.objects.filter(id=wizard_charity_id).first() if wizard_charity_id else None
    )

    context = {"step": step, "wizard_data": wizard_data, "wizard_charity": wizard_charity}

    # Services metadata for the Step 2 template loop
    services_meta = [
        ("QR Generation", "enable_qr_generation", 150, "Campaign-wide QR codes"),
        ("Batch Processing", "enable_batch_processing", 200, "Multi-batch automation"),
        ("Email Sign Off", "enable_email_sign_off", 50, "Custom sign-off review"),
        ("VO Amends", "enable_pers_vo_amends", 55, "Voiceover script changes"),
        ("Text Amends", "enable_text_amends", 30, "Landing page text changes"),
        ("RE-proof", "enable_re_proof", 30, "Second stage proofing"),
        ("Add. Programming", "enable_add_programming", 120, "Custom logic requests"),
        ("Data Cleaning", "enable_data_cleaning", 60, "Formatting & cleansing"),
        ("Audio Cleanup", "enable_audio_cleanup", 65, "Client audio optimization"),
        ("Analytics Report", "enable_analytics_report", 30, "Full insight breakdown"),
        ("Bounce Log", "enable_bounce_log", 30, "Error tracking report"),
        ("Donate Page", "enable_add_donate_page", 50, "Additional landing page"),
    ]
    context["services_meta"] = services_meta

    if request.method == "POST":
        action = request.POST.get("action", "next")
        if action == "back":
            step = max(1, step - 1)
        elif action == "cancel":
            request.session.pop("invoice_wizard_step", None)
            request.session.pop("invoice_wizard_data", None)
            return redirect("dashboard")
        elif step == 1 and action == "next":
            form = InvoiceStep1Form(request.POST, charity=wizard_charity)
            if form.is_valid():
                d = form.cleaned_data
                campaign = d["campaign"]
                start_date = d["billing_start_date"]
                end_date = d["billing_end_date"]

                # Auto-detect personalization from campaign's video mode
                is_personalized = campaign.is_personalized

                # Auto-calculate volume from DonationJob records in the date range
                campaign_volume = DonationJob.objects.filter(
                    campaign=campaign,
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date,
                ).count()

                # Auto-calculate CSV file count (exclude manual entries), £10/file
                auto_csv_file_qty = (
                    DonationBatch.objects.filter(
                        campaign=campaign,
                        created_at__date__gte=start_date,
                        created_at__date__lte=end_date,
                    )
                    .exclude(csv_filename__icontains="manual_entry")
                    .count()
                )

                # Auto-set one-time package defaults from campaign type
                auto_vdm_package = "standard" if campaign.campaign_type == campaign.CampaignType.VDM else "none"
                auto_gratitude_card = campaign.campaign_type == campaign.CampaignType.THANK_YOU

                wizard_data.update(
                    {
                        "client_id": str(d["client"].id),
                        "campaign_id": str(campaign.id),
                        "campaign_name": campaign.name,
                        "campaign_type": campaign.campaign_type or "",
                        "period_start": str(start_date),
                        "period_end": str(end_date),
                        "campaign_volume": campaign_volume,
                        "is_personalized": is_personalized,
                        # Legacy field kept for Invoice model compatibility
                        "pricing_tier": "premium" if is_personalized else "standard",
                        "due_days": d["payment_due_days"],
                        "billing_email": d["billing_email"],
                        "billing_address": d["billing_address"],
                        # Auto-detected defaults for Step 2
                        "auto_csv_file_qty": auto_csv_file_qty,
                        "auto_vdm_package": auto_vdm_package,
                        "auto_gratitude_card": auto_gratitude_card,
                    }
                )
                wizard_data["base_campaign_price"] = get_slab_price(
                    campaign_volume, is_personalized
                )
                step = 2
            else:
                context["form"] = form
        elif step == 2 and action == "next":
            form = InvoiceStep2Form(request.POST)
            if form.is_valid():
                d = form.cleaned_data
                wizard_data.update(
                    {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in d.items()}
                )

                # Logic to generate line items...
                line_items = []
                raw_base = wizard_data.get("base_campaign_price")
                is_poa = raw_base == "POA"
                base_price = 0.0 if is_poa else float(raw_base or 0)
                campaign_desc = wizard_data.get("campaign_name", "")
                base_description = (
                    f"Campaign Charge — POA ({campaign_desc})"
                    if is_poa
                    else f"Campaign Charge ({campaign_desc})"
                )
                line_items.append(
                    {
                        "description": base_description,
                        "quantity": 1,
                        "unit_price": base_price,
                        "total": base_price,
                    }
                )
                if d["setup_costs"] > 0:
                    line_items.append(
                        {
                            "description": "Set up costs",
                            "quantity": 1,
                            "unit_price": float(d["setup_costs"]),
                            "total": float(d["setup_costs"]),
                        }
                    )

                service_prices = [
                    ("enable_email_sign_off", "Email sign off", 50.0),
                    ("enable_pers_vo_amends", "Personalisation & voiceover amends", 55.0),
                    ("enable_text_amends", "Text amends", 30.0),
                    ("enable_re_proof", "RE-proof", 30.0),
                    ("enable_add_programming", "Additional programming", 120.0),
                    ("enable_data_cleaning", "Reformatting of data & cleaning", 60.0),
                    (
                        "enable_audio_cleanup",
                        "Client supplied audio recording clean up/edits",
                        65.0,
                    ),
                    ("enable_analytics_report", "Analytics report", 30.0),
                    ("enable_bounce_log", "Bounce back error log", 30.0),
                    ("enable_bounce_foc", "Bounce back email (FOC)", 0.0),
                    ("enable_qr_generation", "QR Code Generation (Campaign)", 150.0),
                    ("enable_batch_processing", "Batch Processing Service", 200.0),
                    ("enable_add_donate_page", "Additional donate page", 50.0),
                ]
                for field, name, price in service_prices:
                    if d.get(field):
                        qty = max(1, int(request.POST.get(f"{field}_qty") or 1))
                        line_items.append(
                            {
                                "description": name,
                                "quantity": qty,
                                "unit_price": price,
                                "total": price * qty,
                            }
                        )

                if d["csv_file_qty"] > 0:
                    line_items.append(
                        {
                            "description": "Receipt of CSV file",
                            "quantity": d["csv_file_qty"],
                            "unit_price": 10.0,
                            "total": float(d["csv_file_qty"] * 10),
                        }
                    )
                if d["vdm_package"] == "standard":
                    line_items.append(
                        {
                            "description": "Video Direct Mail (VDM) Package",
                            "quantity": 1,
                            "unit_price": 575.0,
                            "total": 575.0,
                        }
                    )
                elif d["vdm_package"] == "client_supplied":
                    line_items.append(
                        {
                            "description": "VDM (Client Supplies Video/Audio)",
                            "quantity": 1,
                            "unit_price": 450.0,
                            "total": 450.0,
                        }
                    )
                if d["enable_gratitude_card"]:
                    line_items.append(
                        {
                            "description": "Gratitud-E Card Package",
                            "quantity": 1,
                            "unit_price": 250.0,
                            "total": 250.0,
                        }
                    )
                if d["video_stock_cost"] > 0:
                    line_items.append(
                        {
                            "description": "Video Stock Cost",
                            "quantity": 1,
                            "unit_price": float(d["video_stock_cost"]),
                            "total": float(d["video_stock_cost"]),
                        }
                    )
                if d["audio_stock_cost"] > 0:
                    line_items.append(
                        {
                            "description": "Audio Stock Cost",
                            "quantity": 1,
                            "unit_price": float(d["audio_stock_cost"]),
                            "total": float(d["audio_stock_cost"]),
                        }
                    )

                wizard_data["line_items"] = line_items
                step = 3
            else:
                context["form"] = form
        elif step == 3 and action == "finalize":
            target_charity = Charity.objects.get(id=wizard_data["client_id"])
            target_campaign = Campaign.objects.filter(id=wizard_data["campaign_id"]).first()
            invoice = Invoice.objects.create(
                charity=target_charity,
                campaign=target_campaign,
                amount=0,
                issue_date=timezone.now().date(),
                due_date=timezone.now().date()
                + timedelta(days=int(wizard_data.get("due_days", 30))),
                period_start=wizard_data.get("period_start"),
                period_end=wizard_data.get("period_end"),
                invoice_type="campaign_wise",
                pricing_tier=wizard_data.get("pricing_tier", "standard"),
                campaign_volume=wizard_data.get("campaign_volume", 0),
                tax_percent=20.00,
                billing_email=wizard_data.get("billing_email")
                or target_charity.billing_email
                or target_charity.contact_email
                or "",
                billing_address=wizard_data.get("billing_address")
                or target_charity.billing_address
                or "",
            )
            invoice.generate_invoice_number()
            invoice.save()

            item_names, item_qtys, item_units = (
                request.POST.getlist("item_name[]"),
                request.POST.getlist("item_qty[]"),
                request.POST.getlist("item_unit[]"),
            )
            for n, q, u in zip(item_names, item_qtys, item_units, strict=False):
                try:
                    qty, unit = float(q), float(u)
                    total = qty * unit
                    if total > 0 or qty > 0:
                        InvoiceLineItem.objects.create(
                            invoice=invoice,
                            description=n,
                            quantity=qty,
                            unit_price=unit,
                            total_amount=total,
                        )
                except Exception:
                    continue
            # Delegate all total calculations (subtotal → tax → amount) to the
            # service layer so the logic stays in one place.
            invoice.calculate_totals()
            request.session.pop("invoice_wizard_step", None)
            request.session.pop("invoice_wizard_data", None)
            messages.success(request, f"Invoice {invoice.invoice_number} created successfully.")
            return redirect("invoice_detail", invoice_id=invoice.id)

        request.session["invoice_wizard_step"] = step
        request.session["invoice_wizard_data"] = wizard_data
        context.update({"step": step, "wizard_data": wizard_data})

    if step == 1:
        initial = {
            k: wizard_data.get(k)
            for k in [
                "client_id",
                "campaign_id",
                "period_start",
                "period_end",
                "due_days",
                "billing_email",
                "billing_address",
            ]
        }
        initial["client"] = initial.pop("client_id")
        initial["campaign"] = initial.pop("campaign_id")
        if "form" not in context:
            context["form"] = InvoiceStep1Form(initial=initial, charity=wizard_charity)
    elif step == 2:
        if "form" not in context:
            # Pre-populate with auto-detected values on first visit to Step 2.
            # On back-navigation from Step 3, wizard_data already holds the user's
            # selections (csv_file_qty, vdm_package, enable_gratitude_card), so the
            # auto values are only used as fallbacks when those keys are absent.
            step2_initial = dict(wizard_data)
            if "csv_file_qty" not in step2_initial:
                step2_initial["csv_file_qty"] = wizard_data.get("auto_csv_file_qty", 0)
            if "vdm_package" not in step2_initial:
                step2_initial["vdm_package"] = wizard_data.get("auto_vdm_package", "none")
            if "enable_gratitude_card" not in step2_initial:
                step2_initial["enable_gratitude_card"] = wizard_data.get(
                    "auto_gratitude_card", False
                )
            context["form"] = InvoiceStep2Form(initial=step2_initial)
    elif step == 3:
        line_items = wizard_data.get("line_items", [])
        subtotal = sum(item.get("total", 0) for item in line_items)
        tax_amount = (subtotal * 20) / 100
        context.update(
            {
                "line_items": line_items,
                "total_amount": subtotal,
                "tax_amount": tax_amount,
                "grand_total": subtotal + tax_amount,
            }
        )
    return render(request, "create_invoice.html", context)


@login_required(login_url="charity_login")
def invoice_detail_view(request, invoice_id):
    import json

    charity = get_active_charity(request)
    if not charity and not request.user.is_superuser:
        return redirect("dashboard")
    if request.user.is_superuser and not charity:
        invoice = get_object_or_404(Invoice, id=invoice_id)
    else:
        invoice = get_object_or_404(Invoice, id=invoice_id, charity=charity)

    # Build initial recipient list for the send-email modal
    recipients: list[str] = []
    if invoice.billing_email:
        recipients.append(invoice.billing_email)
    if invoice.additional_billing_emails:
        for addr in invoice.additional_billing_emails.split(","):
            addr = addr.strip()
            if addr and addr not in recipients:
                recipients.append(addr)

    return render(
        request,
        "invoice_detail.html",
        {
            "invoice": invoice,
            "send_recipients_json": json.dumps(recipients),
        },
    )


@login_required(login_url="charity_login")
def invoice_edit_view(request, invoice_id):
    charity = get_active_charity(request)
    if not charity and not request.user.is_superuser:
        return redirect("dashboard")
    if request.user.is_superuser and not charity:
        invoice = get_object_or_404(Invoice, id=invoice_id)
    else:
        invoice = get_object_or_404(Invoice, id=invoice_id, charity=charity)

    if request.method == "POST":
        form = InvoiceForm(request.POST, instance=invoice)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.calculate_totals()
            invoice.save()
            messages.success(request, f"Invoice {invoice.invoice_number} updated.")
            return redirect("invoices")
    else:
        form = InvoiceForm(instance=invoice)
    return render(request, "invoice_edit.html", {"form": form, "invoice": invoice})
