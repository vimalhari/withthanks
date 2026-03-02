import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AddMemberForm, ClientSetupForm
from .models import Campaign, Charity, CharityMember
from .utils.access_control import get_active_charity

logger = logging.getLogger(__name__)


@login_required(login_url="charity_login")
def client_create_view(request):
    """Super Admin: Create a new Client (Charity + Admin User)."""
    if not request.user.is_superuser:
        messages.error(request, "Unauthorized action.")
        return redirect("dashboard")
    if request.method == "POST":
        name, email, user, pwd = (
            request.POST.get("client_name"),
            request.POST.get("admin_email"),
            request.POST.get("admin_username"),
            request.POST.get("admin_password"),
        )
        if not (name and user and pwd):
            messages.error(request, "Missing fields.")
            return redirect("client_setup")
        if User.objects.filter(username=user).exists():
            messages.error(request, "Username exists.")
            return redirect("client_setup")
        new_user = User.objects.create_user(username=user, email=email, password=pwd)
        new_charity = Charity.objects.create(
            client_name=name, contact_email=email, organization_name=name
        )
        CharityMember.objects.create(charity=new_charity, user=new_user, role="Admin")
        messages.success(request, f"Client '{name}' created.")
        return redirect("client_setup")
    return redirect("client_setup")


@login_required(login_url="charity_login")
def client_setup_view(request, charity_id=None):
    """Client Setup and Member Management."""
    if request.user.is_superuser:
        charity = get_object_or_404(Charity, id=charity_id) if charity_id else None
        if not charity:
            return render(
                request,
                "client_setup.html",
                {"no_client_selected": True, "add_member_form": AddMemberForm()},
            )
    else:
        charity = get_active_charity(request)
        if not charity:
            messages.error(request, "Access denied.")
            return redirect("dashboard")

    if request.method == "POST":
        if "add_member" in request.POST:
            f = AddMemberForm(request.POST)
            if f.is_valid():
                u, e, p, r = (
                    f.cleaned_data["username"],
                    f.cleaned_data["email"],
                    f.cleaned_data["password"],
                    f.cleaned_data["role"],
                )
                if User.objects.filter(username=u).exists():
                    messages.error(request, "Username exists.")
                else:
                    new_u = User.objects.create_user(username=u, email=e, password=p)
                    CharityMember.objects.create(charity=charity, user=new_u, role=r)
                    messages.success(request, f"User {u} added.")
        else:
            client_form = ClientSetupForm(request.POST, request.FILES, instance=charity)
            if client_form.is_valid():
                client_form.save()
                messages.success(request, "Settings saved.")
        return redirect(request.path)

    return render(
        request,
        "client_setup.html",
        {
            "client_form": ClientSetupForm(instance=charity),
            "add_member_form": AddMemberForm(),
            "members": CharityMember.objects.filter(charity=charity).select_related("user"),
            "charity": charity,
        },
    )


@login_required(login_url="charity_login")
def manage_user_password(request, user_id):
    target_user = get_object_or_404(User, id=user_id)
    charity = get_active_charity(request)
    if (
        not request.user.is_superuser
        and not CharityMember.objects.filter(charity=charity, user=target_user).exists()
    ):
        messages.error(request, "Permission denied.")
        return redirect("client_setup")
    if request.method == "POST":
        pwd = request.POST.get("new_password")
        if pwd:
            target_user.set_password(pwd)
            target_user.save()
            messages.success(request, "Password updated.")
    return redirect("client_setup")


@login_required(login_url="charity_login")
def remove_member(request, member_id):
    member = get_object_or_404(CharityMember, id=member_id)
    if (
        not request.user.is_superuser
        and not CharityMember.objects.filter(
            charity=member.charity, user=request.user, role="Admin"
        ).exists()
    ):
        messages.error(request, "Permission denied.")
    elif member.user == request.user:
        messages.error(request, "Cannot remove yourself.")
    else:
        member.delete()
        messages.success(request, "Member removed.")
    return redirect("client_setup")


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
    clients = (
        Charity.objects.all().order_by("client_name")
        if request.user.is_superuser
        else Charity.objects.filter(id=get_active_charity(request).id)
    )
    data = [
        {
            "id": str(c.id),
            "name": c.client_name,
            "billing_email": c.billing_email or c.contact_email or "",
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
