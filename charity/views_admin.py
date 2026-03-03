from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect

from .models import Campaign, Charity
from .utils.access_control import get_active_charity


@login_required(login_url="charity_login")
def switch_client(request, charity_id):
    if not request.user.is_superuser:
        return redirect("dashboard")
    charity = get_object_or_404(Charity, id=charity_id)
    request.session["active_charity_id"] = str(charity.id)
    return redirect("dashboard")


@login_required(login_url="charity_login")
def clear_client_context(request):
    if not request.user.is_superuser:
        return redirect("dashboard")
    if "active_charity_id" in request.session:
        del request.session["active_charity_id"]
    return redirect("dashboard")


@login_required(login_url="charity_login")
def api_clients(request):
    active_charity = get_active_charity(request)
    clients = (
        Charity.objects.all().order_by("client_name")
        if request.user.is_superuser
        else (
            Charity.objects.filter(id=active_charity.id)
            if active_charity
            else Charity.objects.none()
        )
    )
    client_id = request.GET.get("client_id")
    if client_id:
        clients = clients.filter(id=client_id)
    data = [
        {
            "id": str(c.id),
            "name": c.client_name,
            "billing_email": c.billing_email or c.contact_email or "",
            "billing_address": c.billing_address or "",
        }
        for c in clients
    ]
    return JsonResponse(data, safe=False)


@login_required(login_url="charity_login")
def api_campaigns(request):
    client_id = request.GET.get("client_id")
    campaigns = (
        Campaign.objects.all()
        if request.user.is_superuser
        else Campaign.objects.filter(client=get_active_charity(request))
    )
    if client_id and client_id != "all":
        campaigns = campaigns.filter(client_id=client_id)
    data = [{"id": str(c.id), "name": c.name} for c in campaigns.order_by("name")]
    return JsonResponse(data, safe=False)
