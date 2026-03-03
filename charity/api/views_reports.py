from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from ..analytics_models import CampaignStats
from ..models import Campaign


class CampaignReportAPIView(LoginRequiredMixin, View):
    """
    Returns aggregated report data for a specific campaign.
    """

    def get(self, request, campaign_id, *args, **kwargs):
        # 1. Fetch Campaign
        campaign = get_object_or_404(Campaign, id=campaign_id)

        # 2. Get or Initialize Stats
        stats, _ = CampaignStats.objects.get_or_create(campaign=campaign)

        # Optionally trigger a fresh calculation if requested or if stale
        if request.GET.get("refresh") == "true":
            stats.update_stats()

        # 3. Build Response Data
        data = {
            "total_sent": stats.total_sent,
            "total_failed": stats.total_failed,
            "total_opens": stats.total_opens,
            "unique_opens": stats.unique_opens,
            "total_clicks": stats.total_clicks,
            "total_video_views": stats.total_video_views,
            "avg_watch_duration": stats.avg_watch_duration,
            "total_watch_time": stats.total_watch_time,
            "completion_rate": stats.completion_rate,
        }

        # 4. Conditional logic for VDM-only metrics
        if campaign.campaign_type == "VDM":
            data["total_unsubs"] = stats.total_unsubs
        else:
            # For THANKYOU campaigns, ensure unsub metrics aren't leaked
            # The user requested to "Hide Unsubscribe tracking" for THANKYOU
            data["total_unsubs"] = None  # or omit entirely

        return JsonResponse(data)
