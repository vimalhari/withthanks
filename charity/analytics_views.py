from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import DonationJob, Campaign, DonationBatch, Invoice
from .models_analytics import VideoEvent, EmailEvent, WatchSession
import json

@csrf_exempt
def api_track_video_event(request):
    """
    API endpoint for frontend to track video engagement events.
    Expected POST data: {
        'job_id': '...',
        'event_type': 'play_started' | '25_percent', etc.
        'duration_seconds': 123,
        'session_id': '...' (optional)
    }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        job_id = data.get('job_id')
        event_type = data.get('event_type')
        duration = data.get('duration_seconds', 0)
        session_id = data.get('session_id')
        
        job = get_object_or_404(DonationJob, id=job_id)
        
        # Get or create session
        session = None
        if session_id:
            try:
                session = WatchSession.objects.get(id=session_id)
            except WatchSession.DoesNotExist:
                pass
        
        if not session:
            session = WatchSession.objects.create(
                job=job,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT'),
            )
            session_id = str(session.id)

        # Log event
        VideoEvent.objects.create(
            session=session,
            job=job,
            campaign=job.campaign,
            event_type=event_type,
            duration_seconds=duration
        )
        
        # Update session total duration if it's a heartbeat or completion
        if event_type in ['watch_heartbeat', '100_percent'] and duration > session.total_seconds_watched:
            session.total_seconds_watched = duration
            session.save(update_fields=['total_seconds_watched'])

        return JsonResponse({'status': 'success', 'session_id': session_id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
def track_open(request):
    """
    Tracking pixel for email opens.
    """
    job_id = request.GET.get('u')
    if job_id:
        try:
            job = DonationJob.objects.get(id=job_id)
            EmailEvent.objects.create(
                job=job,
                campaign=job.campaign,
                batch=job.donation_batch,
                event_type='opened',
                provider_status='tracking_pixel'
            )
            # Legacy counter update
            job.real_views += 1
            job.save(update_fields=['real_views'])
        except DonationJob.DoesNotExist:
            pass

    # Transparent 1x1 pixel
    pixel = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT"
        b"\x08\xd76\xcf\xb7\r\x00\x00\x00\x82\x00\x81\r\n"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return HttpResponse(pixel, content_type="image/png")

def track_click(request):
    """
    Wraps links to track clicks before redirecting.
    """
    job_id = request.GET.get('u')
    # target_url logic would go here if needed, but usually it's the video page
    # For now, we'll just track and redirect to dashboard (or wherever the video is)
    
    if job_id:
        try:
            job = DonationJob.objects.get(id=job_id)
            EmailEvent.objects.create(
                job=job,
                campaign=job.campaign,
                batch=job.donation_batch,
                event_type='clicked'
            )
            # Legacy counter update
            job.real_clicks += 1
            job.save(update_fields=['real_clicks'])
            
            # Redirect to the video URL
            if job.video_path:
                return JsonResponse({'redirect_url': job.video_path}) # Or handle actual redirect
        except DonationJob.DoesNotExist:
            pass
            
    return JsonResponse({'error': 'Invalid request'}, status=400)
@csrf_exempt
def track_invoice_open(request, invoice_id):
    """
    Tracking pixel for invoice email opens.
    """
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        if not invoice.email_opened_at:
            invoice.email_opened_at = timezone.now()
            invoice.save(update_fields=['email_opened_at'])
    except Exception as e:
        logger.warning(f"track_invoice_open: could not record open for invoice {invoice_id}: {e}")

    # Transparent 1x1 pixel
    pixel = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDAT"
        b"\x08\xd76\xcf\xb7\r\x00\x00\x00\x82\x00\x81\r\n"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return HttpResponse(pixel, content_type="image/png")
