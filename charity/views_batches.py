import csv
import logging
import uuid
import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q, Count, Sum, Avg
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models.functions import TruncDate

from .models import Charity, DonationJob, DonationBatch, Campaign, UnsubscribedUser, ReceivedEmail
from .models_analytics import EmailEvent, VideoEvent, UnsubscribeEvent
from .tasks import process_donation_row, batch_process_csv
from .utils.access_control import get_active_charity
from .utils.metrics_sim import simulate_batch_engagement

logger = logging.getLogger(__name__)

def get_col(row, *keys):
    """Flexibly grab a CSV column (case-insensitive)."""
    for k in keys:
        for key in row.keys():
            if key and key.strip().lower() == k.strip().lower():
                val = row.get(key)
                if val: return val.strip()
    return ""

@login_required(login_url="charity_login")
def upload_csv_and_process(request):
    """Upload CSV and enqueue Celery tasks (Standard + Campaign Blast)."""
    current_charity = get_active_charity(request)
    if not current_charity:
        return redirect('dashboard' if request.user.is_superuser else 'client_setup')

    if request.method == "POST":
        # MODE 1: CAMPAIGN BLAST
        if 'subject' in request.POST and 'csv_file' not in request.FILES:
            subject = request.POST.get('subject')
            new_batch_number = DonationBatch.get_next_batch_number(current_charity)
            batch = DonationBatch.objects.create(charity=current_charity, batch_number=new_batch_number, csv_filename=f"Campaign: {subject}", campaign_name=subject)
            
            previous_donors = DonationJob.objects.filter(charity=current_charity).values('email').annotate(name=Max('donor_name'), last_amount=Max('donation_amount'))
            queued_count = 0
            for donor in previous_donors:
                job = DonationJob.objects.create(donor_name=donor['name'] or 'Supporter', email=donor['email'], charity=current_charity, status="pending", donation_batch=batch)
                process_donation_row.apply_async(args=(job.id,))
                queued_count += 1
            messages.success(request, f"Started campaign '{subject}' for {queued_count} supporters.")
            return redirect('dashboard')

        # MODE 2: CSV UPLOAD
        if request.FILES.get("csv_file"):
            csv_file = request.FILES["csv_file"]
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            
            new_batch_number = DonationBatch.get_next_batch_number(current_charity)
            donation_batch = DonationBatch.objects.create(charity=current_charity, batch_number=new_batch_number, csv_filename=csv_file.name)
            
            campaign_id = request.POST.get("campaign_id")
            if campaign_id:
                donation_batch.campaign = Campaign.objects.filter(id=campaign_id, client=current_charity).first()

            file_name = f"uploads/csv/{uuid.uuid4()}_{csv_file.name}"
            saved_path = default_storage.save(file_name, ContentFile(csv_file.read()))
            donation_batch.csv_filename = saved_path
            donation_batch.save()
            
            batch_process_csv.apply_async(args=(donation_batch.id,))
            messages.success(request, f"CSV '{csv_file.name}' accepted for background processing.")
            return redirect('dashboard')

    last_jobs = DonationJob.objects.filter(donation_batch__charity=current_charity).order_by("-created_at")[:25]
    return render(request, "upload_csv.html", {"jobs": last_jobs})

@login_required(login_url="charity_login")
def send_email_wizard(request):
    """Multi-step wizard for sending emails."""
    current_charity = get_active_charity(request)
    step = int(request.POST.get('step', request.GET.get('step', 1)))
    client_id = request.POST.get('client_id', request.GET.get('client_id'))
    campaign_id = request.POST.get('campaign_id', request.GET.get('campaign_id'))
    method_raw = request.POST.get('method', request.GET.get('method'))
    method = method_raw.strip().lower() if method_raw else None
    
    selected_client = current_charity
    selected_campaign = None
    if campaign_id:
        selected_campaign = get_object_or_404(Campaign, id=campaign_id)
        selected_client = selected_campaign.client
    elif client_id and request.user.is_superuser:
        selected_client = Charity.objects.filter(id=client_id).first()
    
    if not selected_client: selected_client = Charity.objects.filter(members__user=request.user).first()
    campaigns = Campaign.objects.filter(client=selected_client, status__in=['active', 'draft'])

    if request.method == 'POST':
        if step == 4 and method == 'bulk' and 'csv_file' in request.FILES:
            csv_file = request.FILES['csv_file']
            try:
                content = csv_file.read().decode('utf-8-sig')
                lines = content.splitlines()
                reader = csv.DictReader(lines)
                if reader.fieldnames: reader.fieldnames = [h.strip().replace("\ufeff", "") for h in reader.fieldnames]
                csv_data = [row for row in reader if any(row.values())]
                request.session['wizard_csv_data'] = csv_data
                request.session['wizard_csv_filename'] = csv_file.name
                messages.info(request, f"Captured {len(csv_data)} recipients.")
            except Exception as e:
                messages.error(request, f"Error reading CSV: {e}"); step = 3
        
        if step == 5:
            subject = request.POST.get('subject')
            batch = DonationBatch.objects.create(charity=selected_client, campaign=selected_campaign, batch_number=DonationBatch.get_next_batch_number(selected_client), campaign_name=subject)
            queued_count = 0
            
            if method == 'reengage':
                previous_donors = DonationJob.objects.filter(charity=selected_client).values('email').annotate(name=Max('donor_name'))
                for donor in previous_donors:
                    job = DonationJob.objects.create(donor_name=donor['name'] or 'Supporter', email=donor['email'], charity=selected_client, campaign=selected_campaign, status="pending", donation_batch=batch)
                    process_donation_row.apply_async(args=(job.id,))
                    queued_count += 1
            elif method == 'single':
                job = DonationJob.objects.create(donor_name=request.POST.get('recipient_name') or 'Supporter', email=request.POST.get('recipient_email'), charity=selected_client, campaign=selected_campaign, status="pending", donation_batch=batch)
                process_donation_row.apply_async(args=(job.id,)); queued_count = 1
            elif method == 'bulk' and 'wizard_csv_data' in request.session:
                for row in request.session['wizard_csv_data']:
                    name, email = get_col(row, "name", "donor name"), get_col(row, "email", "email address")
                    if email:
                        job = DonationJob.objects.create(donor_name=name or "Donor", email=email, charity=selected_client, campaign=selected_campaign, status="pending", donation_batch=batch)
                        process_donation_row.apply_async(args=(job.id,)); queued_count += 1
            
            if request.POST.get('simulate_metrics') == 'on': simulate_batch_engagement(batch.id)
            messages.success(request, f"Wizard complete: {queued_count} emails queued.")
            return redirect('dashboard')

    context = {
        'step': step, 
        'selected_client': selected_client, 
        'selected_campaign': selected_campaign, 
        'method': method, 
        'campaigns': campaigns,
        'subject': request.POST.get('subject', ''),
        'media_type': request.POST.get('media_type', 'video'),
        'campaign_id': campaign_id,
        'cta_url': request.POST.get('cta_url', ''),
        'recipient_name': request.POST.get('recipient_name', ''),
        'recipient_email': request.POST.get('recipient_email', '')
    }
    return render(request, "send_email_wizard.html", context)

@login_required(login_url="charity_login")
def batch_detail_view(request, batch_id):
    """Detailed stats for a specific batch."""
    current_charity = get_active_charity(request)
    if request.user.is_superuser and not current_charity: batch = get_object_or_404(DonationBatch, id=batch_id)
    else: batch = get_object_or_404(DonationBatch, id=batch_id, charity=current_charity)
    
    if request.method == 'POST' and request.POST.get('action') == 'simulate_views':
        simulate_batch_engagement(batch.id)
        return redirect('batch_detail', batch_id=batch_id)

    jobs = batch.jobs.all()
    stats = jobs.aggregate(total_real=Sum('real_views'), total_fake=Sum('fake_views'), total_videos=Count('id'), success_count=Count('id', filter=Q(status='success')))
    
    video_events = VideoEvent.objects.filter(job__donation_batch=batch)
    engagement = video_events.aggregate(total_plays=Count('id', filter=Q(event_type='play_started')), completions=Count('id', filter=Q(event_type='100_percent')))
    
    email_events = EmailEvent.objects.filter(job__donation_batch=batch)
    delivery_breakdown = email_events.values('event_type').annotate(count=Count('id'))
    bounced_logs = email_events.filter(event_type='bounced').select_related('job')
    
    daily_sent = email_events.filter(event_type='sent').annotate(date=TruncDate('timestamp')).values('date').annotate(count=Count('id')).order_by('date')
    chart_data = {'labels': [d['date'].strftime("%Y-%m-%d") for d in daily_sent], 'sent': [d['count'] for d in daily_sent]}

    return render(request, "batch_report.html", {
        "batch": batch, "stats": stats, "jobs": jobs, "bounced_logs": bounced_logs,
        "delivery_breakdown": list(delivery_breakdown), "chart_data": json.dumps(chart_data)
    })

@login_required(login_url="charity_login")
def export_donation_report(request):
    """Export DonationJob records as CSV."""
    current_charity = get_active_charity(request)
    if not current_charity and not request.user.is_superuser: return redirect('client_setup')
    
    jobs = DonationJob.objects.filter(donation_batch__charity=current_charity) if current_charity else DonationJob.objects.all()
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="donation_report.csv"'
    writer = csv.writer(response)
    writer.writerow(["Date", "Job Name", "Email", "Status", "Total Views"])
    for job in jobs.select_related('donor_name'):
        writer.writerow([job.created_at.strftime("%Y-%m-%d"), job.donor_name, job.email, job.status, job.total_views])
    return response

@login_required(login_url="charity_login")
def batch_tracking_report(request, batch_id):
    """API to return JSON report for a batch."""
    from .models import EmailTracking
    stats = EmailTracking.objects.filter(batch_id=batch_id).aggregate(
        total_sent=Count('id'), opened_count=Count('id', filter=Q(opened=True)), clicked_count=Count('id', filter=Q(clicked=True))
    )
    return JsonResponse(stats)
