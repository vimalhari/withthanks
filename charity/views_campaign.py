from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import Campaign, PackageCode, Charity, DonationJob, EmailTracking
from django.utils import timezone
from django.db.models import Count, Avg, Q
from datetime import datetime
import json

@login_required(login_url="charity_login")
def admin_campaigns(request):
    campaigns = Campaign.objects.all().order_by("-created_at")
    
    # Mock metrics for the dashboard
    metrics = {
        "live_count": campaigns.filter(status="active").count(),
        "total_campaigns": campaigns.count(),
        "total_donations": 0, # Placeholder
        "avg_donation": 0,    # Placeholder
        "total_segments": 0,  # Placeholder
        "top_donors": [],     # Placeholder
        "timeseries": {"labels": [], "data": []} # Placeholder
    }
    
    return render(request, "campaigns/admin_campaigns.html", {
        "campaigns": campaigns,
        "metrics": metrics,
        "metrics_json": json.dumps(metrics)
    })

@login_required(login_url="charity_login")
def campaign_create(request):
    if request.method == "POST":
        try:
            campaign = Campaign.objects.create(
                name=request.POST.get("title"),
                client=get_object_or_404(Charity, id=request.POST.get("client_id")),
                description=request.POST.get("description", ""),
                appeal_code=request.POST.get("appeal_code"),
                appeal_type=request.POST.get("appeal_type"),
                appeal_start=datetime.strptime(request.POST.get("appeal_start"), "%d/%m/%Y").date() if request.POST.get("appeal_start") else timezone.now().date(),
                appeal_end=datetime.strptime(request.POST.get("appeal_end"), "%d/%m/%Y").date() if request.POST.get("appeal_end") else timezone.now().date(),

                is_personalized=request.POST.get("is_personalized") == "on",
                from_email=request.POST.get("from_email") or None,
                charity_video=request.FILES.get("charity_video"),
                gratitude_video=request.FILES.get("gratitude_video"),
                voiceover_script_override=request.POST.get("voiceover_script_override", ""),
                status=request.POST.get("campaign_status", "draft")
            )
        except Exception as e:
            messages.error(request, f"Error creating campaign: {str(e)}")
            return render(request, "campaigns/create_campaign.html", {
                "clients": Charity.objects.all(),
                "error": str(e)
            })

        messages.success(request, f"Campaign '{campaign.name}' created successfully.")
        return redirect("campaign_detail", campaign_id=campaign.id)

    clients = Charity.objects.all()
    return render(request, "campaigns/create_campaign.html", {"clients": clients})

@login_required(login_url="charity_login")
def campaign_detail(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)
    fields = campaign.fields.all()
    
    # Aggregate Metrics from all associated batches
    batches = campaign.batches.all().prefetch_related('jobs')
    
    total_reach = 0
    total_views = 0
    total_success = 0
    total_failed = 0
    total_pending = 0
    total_unsubscribes = 0
    
    for batch in batches:
        total_reach += batch.total_records
        total_success += batch.success_count
        total_failed += batch.failed_count
        total_pending += batch.pending_count
        # Total views across all jobs in this campaign
        from django.db.models import Sum, F
        job_stats = batch.jobs.aggregate(
            total_v=Sum(F('real_views') + F('fake_views'))
        )
        total_views += job_stats['total_v'] or 0
        # Count unsubscribes triggered by jobs in this campaign
        total_unsubscribes += batch.jobs.filter(unsubscribes_triggered__isnull=False).distinct().count()

    # Video Engagement Stats (New)
    engagement_stats = EmailTracking.objects.filter(campaign=campaign).aggregate(
        plays=Count('id', filter=Q(video_played=True)),
        completions=Count('id', filter=Q(video_completed=True)),
        avg_duration=Avg('video_watch_duration')
    )
    
    total_plays = engagement_stats['plays'] or 0
    total_completions = engagement_stats['completions'] or 0
    avg_duration = round(engagement_stats['avg_duration'] or 0, 1)
    completion_rate = round((total_completions / total_plays * 100), 1) if total_plays > 0 else 0

    engagement_rate = 0
    if total_reach > 0:
        engagement_rate = round((total_plays / total_reach) * 100, 1)

    metrics = {
        'total_reach': total_reach,
        'total_views': total_views,
        'total_plays': total_plays,
        'avg_duration': avg_duration,
        'completion_rate': completion_rate,
        'engagement_rate': engagement_rate,
        'success_count': total_success,
        'failed_count': total_failed,
        'pending_count': total_pending,
        'total_unsubscribes': total_unsubscribes,
        'batch_count': batches.count()
    }
    
    from django.core.paginator import Paginator
    per_page = request.GET.get('per_page', 25)
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 25
        
    paginator = Paginator(batches, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, "campaigns/campaign_detail.html", {
        "campaign": campaign,
        "fields": fields,
        "batches": page_obj,
        "page_obj": page_obj,
        "per_page": per_page,
        "metrics": metrics
    })

@login_required(login_url="charity_login")
def campaign_edit(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)
    
    if request.method == "POST":
        campaign.name = request.POST.get("title")
        campaign.appeal_code = request.POST.get("appeal_code")
        campaign.appeal_type = request.POST.get("appeal_type")

        campaign.is_personalized = request.POST.get("is_personalized") == "on"
        campaign.from_email = request.POST.get("from_email") or None
        campaign.description = request.POST.get("description", "")
        campaign.status = request.POST.get("status")
        campaign.voiceover_script_override = request.POST.get("voiceover_script_override", "")
        
        if request.FILES.get("video_template_override"):
             campaign.video_template_override = request.FILES.get("video_template_override")

        # NEW MEDIA ASSETS
        if request.FILES.get("charity_video"):
             campaign.charity_video = request.FILES.get("charity_video")
        
        if request.FILES.get("gratitude_video"):
             campaign.gratitude_video = request.FILES.get("gratitude_video")
        
        if request.POST.get("appeal_start"):
            campaign.appeal_start = datetime.strptime(request.POST.get("appeal_start"), "%d/%m/%Y").date()
        if request.POST.get("appeal_end"):
            campaign.appeal_end = datetime.strptime(request.POST.get("appeal_end"), "%d/%m/%Y").date()
            
        campaign.save()
        
        messages.success(request, f"Campaign '{campaign.name}' updated.")
        return redirect("campaign_detail", campaign_id=campaign.id)

    clients = Charity.objects.all()
    status_choices = Campaign.STATUS_CHOICES
    appeal_types = [
        ("WithThanks", "Thank you"),
        ("VDM", "Video Direct Mail (VDM)"),
    ]
    
    return render(request, "campaigns/edit_campaign.html", {
        "campaign": campaign,
        "clients": clients,
        "status_choices": status_choices,
        "appeal_types": appeal_types,
    })

@login_required(login_url="charity_login")
def campaign_fields(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)
    fields = campaign.fields.all()
    field_types = CampaignField.FIELD_TYPES
    
    return render(request, "campaigns/manage_fields.html", {
        "campaign": campaign,
        "fields": fields,
        "field_types": field_types
    })

@login_required(login_url="charity_login")
def campaign_field_add(request, campaign_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)
    if request.method == "POST":
        label = request.POST.get("label")
        field_type = request.POST.get("field_type")
        required = request.POST.get("required") == "on"
        options_raw = request.POST.get("options", "")
        options = [o.strip() for o in options_raw.split(",") if o.strip()]
        
        last_field = campaign.fields.last()
        order = (last_field.order + 1) if last_field else 0
        
        CampaignField.objects.create(
            campaign=campaign,
            label=label,
            field_type=field_type,
            required=required,
            options=options,
            order=order
        )
        messages.success(request, f"Field '{label}' added.")
    return redirect("campaign_fields", campaign_id=campaign.id)

@login_required(login_url="charity_login")
def campaign_field_delete(request, campaign_id, field_id):
    campaign = get_object_or_404(Campaign, id=campaign_id)
    field = get_object_or_404(CampaignField, id=field_id, campaign=campaign)
    if request.method == "POST":
        field.delete()
        messages.success(request, f"Field '{field.label}' deleted.")
    return redirect("campaign_fields", campaign_id=campaign.id)
