from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect

from .models import Campaign, Charity
from .utils.access_control import get_active_charity


@login_required(login_url="charity_login")
def switch_charity(request, charity_id):
    if not request.user.is_superuser:
        return redirect("dashboard")
    charity = get_object_or_404(Charity, id=charity_id)
    request.session["active_charity_id"] = str(charity.id)
    return redirect("dashboard")


@login_required(login_url="charity_login")
def clear_charity_context(request):
    if not request.user.is_superuser:
        return redirect("dashboard")
    if "active_charity_id" in request.session:
        del request.session["active_charity_id"]
    return redirect("dashboard")


@login_required(login_url="charity_login")
def api_charities(request):
    active_charity = get_active_charity(request)
    charities = (
        Charity.objects.all().order_by("charity_name")
        if request.user.is_superuser
        else (
            Charity.objects.filter(id=active_charity.id)
            if active_charity
            else Charity.objects.none()
        )
    )
    charity_id = request.GET.get("charity_id")
    if charity_id:
        charities = charities.filter(id=charity_id)
    data = [
        {
            "id": str(c.id),
            "name": c.charity_name,
            "billing_email": c.billing_email or c.contact_email or "",
            "billing_address": c.formatted_billing_address,
        }
        for c in charities
    ]
    return JsonResponse(data, safe=False)


@login_required(login_url="charity_login")
def api_campaigns(request):
    charity_id = request.GET.get("charity_id")
    campaigns = (
        Campaign.objects.all()
        if request.user.is_superuser
        else Campaign.objects.filter(charity=get_active_charity(request))
    )
    if charity_id and charity_id != "all":
        campaigns = campaigns.filter(charity_id=charity_id)
    data = [{"id": str(c.id), "name": c.name} for c in campaigns.order_by("name")]
    return JsonResponse(data, safe=False)
