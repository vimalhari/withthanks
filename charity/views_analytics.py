import time
from datetime import datetime, timedelta

import jwt  # PyJWT
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView, View

from .models import Campaign, Charity, CharityMember
from .models_analytics import CampaignStats, EmailEvent, VideoEvent
from .utils.exports import export_analytics_csv, export_analytics_excel


class AnalyticsPermissionMixin(UserPassesTestMixin):
    def test_func(self):
        if self.request.user.is_superuser:
            return True
        return CharityMember.objects.filter(user=self.request.user, status="ACTIVE").exists()


class AnalyticsBaseView(LoginRequiredMixin, AnalyticsPermissionMixin, TemplateView):
    def get_date_range(self):
        days = self.request.GET.get("days", "30")
        end_date = timezone.now()
        try:
            start_date = end_date - timedelta(days=int(days))
        except ValueError:
            start_date = end_date - timedelta(days=30)
        return start_date, end_date

    def get_filtered_queryset(self, model_class):
        qs = model_class.objects.all()
        if not self.request.user.is_superuser:
            # Get charities this user belongs to
            user_charity_ids = CharityMember.objects.filter(
                user=self.request.user, status="ACTIVE"
            ).values_list("charity_id", flat=True)

            if model_class == EmailEvent:
                qs = qs.filter(batch__charity_id__in=user_charity_ids)
            elif model_class == VideoEvent:
                qs = qs.filter(job__donation_batch__charity_id__in=user_charity_ids)
            elif model_class == Campaign:
                qs = qs.filter(charity_id__in=user_charity_ids)
        return qs


class UnifiedAnalyticsView(AnalyticsBaseView):
    template_name = "analytics/unified_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get list of clients/charities for filtering
        if self.request.user.is_superuser:
            context["clients"] = Charity.objects.all().order_by("client_name")
        else:
            user_charity_ids = CharityMember.objects.filter(
                user=self.request.user, status="ACTIVE"
            ).values_list("charity_id", flat=True)
            context["clients"] = Charity.objects.filter(id__in=user_charity_ids).order_by(
                "client_name"
            )

        return context


class UnifiedDashboardDataAPI(AnalyticsBaseView, View):
    def get(self, request, *args, **kwargs):
        charity_id = request.GET.get("charity_id")
        campaign_id = request.GET.get("campaign_id")
        days = int(request.GET.get("days", 30))

        if not charity_id or charity_id == "all" or not campaign_id or campaign_id == "all":
            return JsonResponse({"error": "Selection required"}, status=400)

        campaign = get_object_or_404(Campaign, id=campaign_id)

        # 1. Caching Layer (CampaignStats)
        stats, created = CampaignStats.objects.get_or_create(campaign=campaign)
        # Refresh if created or stale (> 10 mins)
        if created or (timezone.now() - stats.last_updated).total_seconds() > 600:
            stats.update_stats()

        # 2. Advanced Weekly/Timeline Logic & Trend Calculation
        start_date, end_date = self.get_date_range()
        duration = end_date - start_date
        prev_start = start_date - duration
        prev_end = start_date

        # Trend Calculations (Previous Period)
        prev_email_qs = EmailEvent.objects.filter(
            campaign=campaign, timestamp__range=(prev_start, prev_end)
        )
        prev_video_qs = VideoEvent.objects.filter(
            campaign=campaign, timestamp__range=(prev_start, prev_end)
        )

        def calc_trend(current, previous):
            if previous == 0:
                return "+0%" if current == 0 else "+100%"
            change = ((current - previous) / previous) * 100
            prefix = "+" if change >= 0 else ""
            return f"{prefix}{round(change, 1)}%"

        prev_sent = prev_email_qs.filter(event_type__in=["SENT", "sent"]).count()
        prev_unique_opens = (
            prev_email_qs.filter(event_type__in=["OPEN", "opened"])
            .values("job_id")
            .distinct()
            .count()
        )
        prev_open_rate = (prev_unique_opens / prev_sent * 100) if prev_sent > 0 else 0

        prev_plays = prev_video_qs.filter(event_type__in=["PLAY", "play_started"]).count()

        trends = {
            "sent": calc_trend(stats.total_sent, prev_sent),
            "open_rate": calc_trend(stats.open_rate, prev_open_rate),
            "plays": calc_trend(stats.total_video_views, prev_plays),
            "click": calc_trend(stats.click_rate, 0),  # Placeholder for more complex ones if needed
        }

        # Grouped Data for Weekly Emails Performance
        # We'll use a simple list of last 4-8 weeks/days depending on range
        timeline = []
        for i in range(days, -1, -1):
            day = end_date.date() - timedelta(days=i)
            day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
            day_end = timezone.make_aware(datetime.combine(day, datetime.max.time()))

            day_qs = EmailEvent.objects.filter(
                campaign=campaign, timestamp__range=(day_start, day_end)
            )
            timeline.append(
                {
                    "label": day.strftime("%b %d"),
                    "sent": day_qs.filter(event_type__in=["SENT", "sent"]).count(),
                    "opened": day_qs.filter(event_type__in=["OPEN", "opened"]).count(),
                    "clicked": day_qs.filter(event_type__in=["CLICK", "clicked"]).count(),
                }
            )

        # 3. Watch Percentage Distribution (0-25%, 25-50%, etc.)
        video_qs = VideoEvent.objects.filter(
            campaign=campaign, timestamp__range=(start_date, end_date)
        )
        dist = {
            "buckets": ["0-25%", "25-50%", "50-75%", "75-100%"],
            "values": [
                video_qs.filter(completion_percentage__gte=0, completion_percentage__lt=25).count(),
                video_qs.filter(
                    completion_percentage__gte=25, completion_percentage__lt=50
                ).count(),
                video_qs.filter(
                    completion_percentage__gte=50, completion_percentage__lt=75
                ).count(),
                video_qs.filter(completion_percentage__gte=75).count(),
            ],
        }

        # 4. Funnel Logic based on Campaign Type
        if campaign.appeal_type == "VDM":
            stages = [
                {"label": "Sent", "value": stats.total_sent},
                {"label": "Delivered", "value": stats.total_sent - stats.total_failed},
                {"label": "Opened", "value": stats.unique_opens},
                {"label": "Clicked", "value": stats.total_clicks},
                {"label": "Played", "value": stats.total_video_views},
                {
                    "label": "50% Watched",
                    "value": video_qs.filter(completion_percentage__gte=50).count(),
                },
                {
                    "label": "Completed",
                    "value": video_qs.filter(event_type__in=["COMPLETE", "100_percent"]).count(),
                },
                {"label": "Unsubscribed", "value": stats.total_unsubs},
            ]
        else:
            stages = [
                {"label": "Sent", "value": stats.total_sent},
                {"label": "Delivered", "value": stats.total_sent - stats.total_failed},
                {"label": "Opened", "value": stats.unique_opens},
                {"label": "Played", "value": stats.total_video_views},
                {
                    "label": "Completed",
                    "value": video_qs.filter(event_type__in=["COMPLETE", "100_percent"]).count(),
                },
            ]

        # 5. Format Duration
        def format_duration(seconds):
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        return JsonResponse(
            {
                "campaign_type": campaign.appeal_type,
                "metrics": {
                    "total_sent": stats.total_sent,
                    "total_failed": stats.total_failed,
                    "total_opened": stats.unique_opens,
                    "total_views": stats.total_opens,
                    "clicked": stats.total_clicks,
                    "unsubs": stats.total_unsubs,
                    "plays": stats.total_video_views,
                    "unique_viewers": stats.unique_viewers,
                    "rewatch_rate": f"{stats.rewatch_rate}%",
                    "avg_watch_time": f"{stats.avg_watch_duration}s",
                    "total_watch_time": format_duration(stats.total_watch_time),
                    "video_completion_rate": f"{stats.completion_rate}%",
                    "open_rate": f"{stats.open_rate}%",
                    "click_rate": f"{stats.click_rate}%",
                    "unsub_rate": f"{stats.unsub_rate}%",
                    "bounce_rate": f"{stats.bounce_rate}%",
                    "trends": trends,
                },
                "charts": {
                    "funnel": {"stages": stages},
                    "timeline": timeline,
                    "distribution": dist,
                    "retention": {
                        "labels": ["0%", "25%", "50%", "75%", "100%"],
                        "values": [
                            stats.total_video_views,
                            video_qs.filter(completion_percentage__gte=25).count(),
                            video_qs.filter(completion_percentage__gte=50).count(),
                            video_qs.filter(completion_percentage__gte=75).count(),
                            video_qs.filter(event_type__in=["COMPLETE", "100_percent"]).count(),
                        ],
                    },
                    "engagement": {
                        "labels": ["Low (<25%)", "Medium (25-50%)", "High (50-75%)", "Full (100%)"],
                        "values": [
                            video_qs.filter(completion_percentage__lt=25).count(),
                            video_qs.filter(
                                completion_percentage__gte=25, completion_percentage__lt=50
                            ).count(),
                            video_qs.filter(
                                completion_percentage__gte=50, completion_percentage__lt=75
                            ).count(),
                            video_qs.filter(completion_percentage__gte=75).count(),
                        ],
                        "colors": ["#f43f5e", "#fbbf24", "#3b82f6", "#10b981"],
                    },
                },
            }
        )


class AnalyticsHomeView(AnalyticsBaseView):
    template_name = "analytics/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date = self.get_date_range()

        email_qs = self.get_filtered_queryset(EmailEvent).filter(
            timestamp__range=(start_date, end_date)
        )
        video_qs = self.get_filtered_queryset(VideoEvent).filter(
            timestamp__range=(start_date, end_date)
        )

        context["stats"] = {
            "total_sent": email_qs.filter(event_type="sent").count(),
            "total_opened": email_qs.filter(event_type="opened").count(),
            "total_plays": video_qs.filter(event_type="play_started").count(),
        }
        return context


class VideoEngagementView(AnalyticsBaseView):
    template_name = "analytics/video.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date = self.get_date_range()
        user_key = "global" if self.request.user.is_superuser else f"user_{self.request.user.id}"
        cache_key = f"analytics_video_{user_key}_{start_date.date()}_{end_date.date()}"

        data = cache.get(cache_key)
        if not data:
            video_qs = self.get_filtered_queryset(VideoEvent).filter(
                timestamp__range=(start_date, end_date)
            )

            # KPI Aggregates
            stats = video_qs.aggregate(
                plays=Count("id", filter=Q(event_type="play_started")),
                q1=Count("id", filter=Q(event_type="25_percent")),
                q2=Count("id", filter=Q(event_type="50_percent")),
                q3=Count("id", filter=Q(event_type="75_percent")),
                comp=Count("id", filter=Q(event_type="100_percent")),
                total_duration=Sum("watch_duration", filter=Q(event_type="PROGRESS")),
            )

            plays = stats["plays"] or 0
            comp = stats["comp"] or 0

            data = {
                "plays": plays,
                "completion_rate": round(comp / plays * 100, 1) if plays > 0 else 0,
                "avg_duration": round(stats["total_duration"] / plays, 1) if plays > 0 else 0,
                "funnel": [plays, stats["q1"] or 0, stats["q2"] or 0, stats["q3"] or 0, comp],
            }
            cache.set(cache_key, data, 300)  # 5 minutes

        context.update(data)
        return context


class DeliveryDashboardView(AnalyticsBaseView):
    template_name = "analytics/delivery.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date = self.get_date_range()
        user_key = "global" if self.request.user.is_superuser else f"user_{self.request.user.id}"
        cache_key = f"analytics_delivery_{user_key}_{start_date.date()}_{end_date.date()}"

        data = cache.get(cache_key)
        if not data:
            email_qs = self.get_filtered_queryset(EmailEvent).filter(
                timestamp__range=(start_date, end_date)
            )

            delivery_stats = email_qs.aggregate(
                sent=Count("id", filter=Q(event_type="sent")),
                delivered=Count("id", filter=Q(event_type="delivered")),
                bounced=Count("id", filter=Q(event_type="bounced")),
                failed=Count("id", filter=Q(event_type="failed")),
                opened=Count("id", filter=Q(event_type="opened")),
            )

            sent = delivery_stats["sent"] or 1  # Avoid div by zero

            data = {
                "sent": delivery_stats["sent"] or 0,
                "delivery_rate": round(delivery_stats["delivered"] / sent * 100, 1),
                "bounce_rate": round(delivery_stats["bounced"] / sent * 100, 1),
                "open_rate": round(delivery_stats["opened"] / sent * 100, 1),
                "errors": list(
                    email_qs.filter(event_type="failed")
                    .values("event_type")
                    .annotate(count=Count("id"))
                    .order_by("-count")[:5]
                ),
            }
            cache.set(cache_key, data, 300)

        context.update(data)
        return context


class CampaignPerformanceView(AnalyticsBaseView):
    template_name = "analytics/campaigns.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date = self.get_date_range()

        campaigns = self.get_filtered_queryset(Campaign)
        perf = []
        for camp in campaigns:
            c_emails = EmailEvent.objects.filter(
                campaign=camp, timestamp__range=(start_date, end_date)
            )
            c_videos = VideoEvent.objects.filter(
                campaign=camp, timestamp__range=(start_date, end_date)
            )

            sent = c_emails.filter(event_type="sent").count()
            opened = c_emails.filter(event_type="opened").count()
            plays = c_videos.filter(event_type="play_started").count()

            if sent > 0:
                perf.append(
                    {
                        "name": camp.name,
                        "sent": sent,
                        "open_rate": round(opened / sent * 100, 1),
                        "play_rate": round(plays / sent * 100, 1),
                    }
                )

        context["campaign_perf"] = perf
        return context


class AdvancedDashboardsView(AnalyticsBaseView):
    template_name = "analytics/metabase_embed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Metabase Embedding Logic
        METABASE_SITE_URL = getattr(settings, "METABASE_SITE_URL", "http://localhost:3000")
        METABASE_SECRET_KEY = getattr(settings, "METABASE_SECRET_KEY", "your_secret_key_here")

        # Example Dashboard ID (should be configurable)
        dashboard_id = 1

        payload = {
            "resource": {"dashboard": dashboard_id},
            "params": {},
            "exp": round(time.time()) + (60 * 10),  # 10 minute expiration
        }

        token = jwt.encode(payload, METABASE_SECRET_KEY, algorithm="HS256")

        # In newer PyJWT, it returns a string. In older ones, it returns bytes.
        if isinstance(token, bytes):
            token = token.decode("utf-8")

        context["iframe_url"] = (
            f"{METABASE_SITE_URL}/embed/dashboard/{token}#bordered=true&titled=true"
        )
        return context


# --- EXPORT & API VIEWS ---


class ExportAnalyticsView(AnalyticsBaseView, View):
    def get(self, request, *args, **kwargs):
        fmt = kwargs.get("format", "csv")
        start_date, end_date = self.get_date_range()

        # Gather data for export
        campaigns = self.get_filtered_queryset(Campaign)
        export_data = []

        for camp in campaigns:
            c_emails = EmailEvent.objects.filter(
                campaign=camp, timestamp__range=(start_date, end_date)
            )
            c_videos = VideoEvent.objects.filter(
                campaign=camp, timestamp__range=(start_date, end_date)
            )

            sent = c_emails.filter(event_type="sent").count()
            if sent == 0:
                continue

            delivered = c_emails.filter(event_type="delivered").count()
            opened = c_emails.filter(event_type="opened").count()
            clicked = c_emails.filter(event_type="clicked").count()
            plays = c_videos.filter(event_type="play_started").count()
            comp = c_videos.filter(event_type="100_percent").count()
            duration = (
                c_videos.filter(event_type="PROGRESS").aggregate(Sum("watch_duration"))[
                    "watch_duration__sum"
                ]
                or 0
            )

            export_data.append(
                {
                    "date": timezone.now().strftime(
                        "%Y-%m-%d"
                    ),  # Grouping by date could be added here
                    "campaign_name": camp.name,
                    "recipients": sent,
                    "delivered": delivered,
                    "opened": opened,
                    "clicked": clicked,
                    "plays": plays,
                    "avg_watch_time": round(duration / plays, 1) if plays > 0 else 0,
                    "completion_rate": round(comp / plays * 100, 1) if plays > 0 else 0,
                }
            )

        filename = f"analytics_export_{timezone.now().strftime('%Y%m%d')}"
        if fmt == "excel":
            return export_analytics_excel(export_data, filename)
        return export_analytics_csv(export_data, filename)


class ChartDataAPIView(AnalyticsBaseView, View):
    def get(self, request, *args, **kwargs):
        chart_type = kwargs.get("chart_type")
        start_date, end_date = self.get_date_range()

        if chart_type == "engagement":
            video_qs = self.get_filtered_queryset(VideoEvent).filter(
                timestamp__range=(start_date, end_date)
            )
            stats = video_qs.aggregate(
                plays=Count("id", filter=Q(event_type="play_started")),
                q1=Count("id", filter=Q(event_type="25_percent")),
                q2=Count("id", filter=Q(event_type="50_percent")),
                q3=Count("id", filter=Q(event_type="75_percent")),
                comp=Count("id", filter=Q(event_type="100_percent")),
            )
            data = {
                "labels": ["Play Started", "25%", "50%", "75%", "100%"],
                "values": [
                    stats["plays"] or 0,
                    stats["q1"] or 0,
                    stats["q2"] or 0,
                    stats["q3"] or 0,
                    stats["comp"] or 0,
                ],
            }
        elif chart_type == "delivery":
            email_qs = self.get_filtered_queryset(EmailEvent).filter(
                timestamp__range=(start_date, end_date)
            )
            stats = email_qs.aggregate(
                delivered=Count("id", filter=Q(event_type="delivered")),
                bounced=Count("id", filter=Q(event_type="bounced")),
                failed=Count("id", filter=Q(event_type="failed")),
            )
            data = {
                "labels": ["Delivered", "Bounced", "Failed"],
                "values": [stats["delivered"] or 0, stats["bounced"] or 0, stats["failed"] or 0],
            }
        else:
            return JsonResponse({"error": "Invalid chart type"}, status=400)

        return JsonResponse(data)
