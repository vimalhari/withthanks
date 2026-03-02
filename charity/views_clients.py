from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required(login_url="charity_login")
def clients_view(request):
    """
    List all clients and handle client onboarding.
    """
    from django.contrib import messages

    from .models import Campaign, Charity, DonationJob

    # Only superusers can access this
    if not request.user.is_superuser:
        messages.error(request, "Unauthorized access.")
        return redirect("dashboard")

    if request.method == "POST":
        # Handle client creation
        client_name = request.POST.get("client_name")
        organization_name = request.POST.get("organization_name")
        contact_email = request.POST.get("contact_email")
        default_voiceover_script = request.POST.get("default_voiceover_script", "")
        default_voice_id = request.POST.get("default_voice_id", "")
        default_template_video = request.FILES.get("default_template_video")

        if not (client_name and organization_name and contact_email):
            messages.error(request, "Please provide all required fields.")
            return redirect("clients")

        try:
            Charity.objects.create(
                client_name=client_name,
                organization_name=organization_name,
                contact_email=contact_email,
                contact_phone=request.POST.get("contact_phone", ""),
                company_number=request.POST.get("company_number", ""),
                address_line_1=request.POST.get("address_line_1", ""),
                address_line_2=request.POST.get("address_line_2", ""),
                county=request.POST.get("county", ""),
                postcode=request.POST.get("postcode", ""),
                default_voiceover_script=default_voiceover_script,
                default_voice_id=default_voice_id,
                default_template_video=default_template_video,
                gratitude_card=request.FILES.get("gratitude_card"),
                blackbaud_client_id=request.POST.get("blackbaud_client_id", ""),
                blackbaud_client_secret=request.POST.get("blackbaud_client_secret", ""),
                blackbaud_enabled=request.POST.get("blackbaud_enabled") == "on",
            )

            messages.success(request, f"Client '{client_name}' onboarded successfully!")
            return redirect("clients")

        except Exception as e:
            messages.error(request, f"Error creating client: {e!s}")
            return redirect("clients")

    # GET request - show clients list
    clients = Charity.objects.all().order_by("-created_at")
    total_campaigns = Campaign.objects.count()
    total_videos = DonationJob.objects.filter(status="success").count()

    return render(
        request,
        "clients.html",
        {
            "clients": clients,
            "total_campaigns": total_campaigns,
            "total_videos": total_videos,
        },
    )


@login_required(login_url="charity_login")
def client_edit_view(request, client_id):
    """
    Dedicated edit page for a specific client.
    """
    from django.contrib import messages
    from django.shortcuts import get_object_or_404

    from .models import Charity

    # Only superusers can access this
    if not request.user.is_superuser:
        messages.error(request, "Unauthorized access.")
        return redirect("dashboard")

    client = get_object_or_404(Charity, id=client_id)

    if request.method == "POST":
        client.client_name = request.POST.get("client_name")
        client.organization_name = request.POST.get("organization_name")
        client.contact_email = request.POST.get("contact_email")
        client.default_voiceover_script = request.POST.get("default_voiceover_script", "")
        client.default_voice_id = request.POST.get("default_voice_id", "")

        if request.FILES.get("default_template_video"):
            client.default_template_video = request.FILES.get("default_template_video")

        if request.FILES.get("gratitude_card"):
            client.gratitude_card = request.FILES.get("gratitude_card")

        client.contact_phone = request.POST.get("contact_phone", "")
        client.company_number = request.POST.get("company_number", "")
        client.address_line_1 = request.POST.get("address_line_1", "")
        client.address_line_2 = request.POST.get("address_line_2", "")
        client.county = request.POST.get("county", "")
        client.postcode = request.POST.get("postcode", "")

        # Blackbaud Integration
        client.blackbaud_client_id = request.POST.get("blackbaud_client_id", "")
        client.blackbaud_client_secret = request.POST.get("blackbaud_client_secret", "")
        client.blackbaud_enabled = request.POST.get("blackbaud_enabled") == "on"

        client.save()
        messages.success(request, f"Client '{client.client_name}' updated successfully!")
        return redirect("clients")

    return render(request, "client_edit.html", {"client": client})


@login_required(login_url="charity_login")
def client_campaign_redirect(request, client_id):
    """
    Smart redirect: Opens existing campaign or creates a default one.
    """
    import datetime

    from django.shortcuts import get_object_or_404
    from django.utils import timezone

    from .models import Campaign, Charity

    # Only superusers for now
    if not request.user.is_superuser:
        return redirect("dashboard")

    client = get_object_or_404(Charity, id=client_id)

    # Check if client has any campaign
    campaign = client.campaigns.first()

    if not campaign:
        # Create a default campaign
        year = timezone.now().year
        campaign = Campaign.objects.create(
            name=f"Primary Campaign - {client.client_name}",
            client=client,
            description=f"Primary fundraising and engagement campaign for {client.client_name}.",
            appeal_code=f"PC-{client.id}-{year}",
            appeal_start=timezone.now().date(),
            appeal_end=timezone.now().date() + datetime.timedelta(days=365),
            open_date=timezone.now().date(),
            close_date=timezone.now().date() + datetime.timedelta(days=365),
            status="active",
        )

    return redirect("campaign_detail", campaign_id=campaign.id)
