from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.db.models import Avg, Count, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView, View

from .analytics_models import CampaignStats, EmailEvent, VideoEvent
from .models import (
    Campaign,
    Charity,
    CharityMember,
    DonationJob,
    Invoice,
    InvoiceLineItem,
    UnsubscribedUser,
    VideoSendLog,
)
from .utils.access_control import (
    get_accessible_charities,
    get_authorized_campaign,
    get_authorized_charity,
)
from .utils.exports import export_analytics_csv, export_analytics_excel

_DATE_FMT = "%Y-%m-%d"
_DEFAULT_DAYS = 90


class AnalyticsPermissionMixin(UserPassesTestMixin):
    def test_func(self):
        if self.request.user.is_superuser:
            return True
        return CharityMember.objects.filter(user=self.request.user, status="ACTIVE").exists()


class AnalyticsBaseView(LoginRequiredMixin, AnalyticsPermissionMixin, TemplateView):
    def get_date_range(self):
        """Parse date_from / date_to GET params (YYYY-MM-DD). Defaults to last 90 days."""
        today = timezone.now().date()
        raw_from = self.request.GET.get("date_from", "")
        raw_to = self.request.GET.get("date_to", "")
        try:
            start = (
                datetime.strptime(raw_from, _DATE_FMT).date()
                if raw_from
                else today - timedelta(days=_DEFAULT_DAYS)
            )
        except ValueError:
            start = today - timedelta(days=_DEFAULT_DAYS)
        try:
            end = datetime.strptime(raw_to, _DATE_FMT).date() if raw_to else today
        except ValueError:
            end = today
        # Convert to timezone-aware datetimes
        start_dt = timezone.make_aware(datetime.combine(start, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(end, datetime.max.time()))
        return start_dt, end_dt

    def get_date_params(self) -> dict:
        """Return date_from/date_to as strings for template context."""
        today = timezone.now().date()
        raw_from = self.request.GET.get(
            "date_from", (today - timedelta(days=_DEFAULT_DAYS)).strftime(_DATE_FMT)
        )
        raw_to = self.request.GET.get("date_to", today.strftime(_DATE_FMT))
        return {"date_from": raw_from, "date_to": raw_to}

    def get_filtered_queryset(self, model_class):
        qs = model_class.objects.all()
        if not self.request.user.is_superuser:
            # Get charities this user belongs to
            user_charity_ids = CharityMember.objects.filter(
                user=self.request.user, status="ACTIVE"
            ).values_list("charity_id", flat=True)

            if model_class in (EmailEvent, VideoEvent):
                qs = qs.filter(
                    Q(job__charity_id__in=user_charity_ids)
                    | Q(campaign__charity_id__in=user_charity_ids)
                ).distinct()
            elif model_class == Campaign:
                qs = qs.filter(charity_id__in=user_charity_ids)
        return qs


class UnifiedAnalyticsView(AnalyticsBaseView):
    template_name = "analytics/unified_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get list of clients/charities for filtering
        if self.request.user.is_superuser:
            context["clients"] = Charity.objects.all().order_by("charity_name")
        else:
            context["clients"] = get_accessible_charities(self.request.user).order_by(
                "charity_name"
            )
        context.update(self.get_date_params())
        return context


class UnifiedDashboardDataAPI(AnalyticsBaseView, View):
    def get(self, request, *args, **kwargs):
        charity_id = request.GET.get("charity_id")
        campaign_id = request.GET.get("campaign_id")

        if not charity_id or charity_id == "all" or not campaign_id or campaign_id == "all":
            return JsonResponse({"error": "Selection required"}, status=400)

        charity = get_authorized_charity(request.user, charity_id)
        campaign = get_authorized_campaign(request.user, campaign_id)
        if charity is None or campaign is None or campaign.charity_id != charity.id:
            raise Http404

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
        total_days = (end_date.date() - start_date.date()).days
        for i in range(total_days, -1, -1):
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
        if campaign.campaign_type == campaign.CampaignType.VDM:
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
                "campaign_type": campaign.campaign_type,
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
            "total_sent": email_qs.filter(event_type="SENT").count(),
            "total_opened": email_qs.filter(event_type="OPEN").count(),
            "total_plays": video_qs.filter(event_type="PLAY").count(),
        }
        context.update(self.get_date_params())
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
                plays=Count("id", filter=Q(event_type="PLAY")),
                q1=Count("id", filter=Q(event_type="PROGRESS", completion_percentage__gte=25)),
                q2=Count("id", filter=Q(event_type="PROGRESS", completion_percentage__gte=50)),
                q3=Count("id", filter=Q(event_type="PROGRESS", completion_percentage__gte=75)),
                comp=Count("id", filter=Q(event_type="COMPLETE")),
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
        context.update(self.get_date_params())
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
                sent=Count("id", filter=Q(event_type="SENT")),
                delivered=Count(
                    "id", filter=Q(event_type="SENT")
                ),  # R2: no separate delivered state
                bounced=Count("id", filter=Q(event_type="BOUNCED")),
                failed=Count("id", filter=Q(event_type="FAILED")),
                opened=Count("id", filter=Q(event_type="OPEN")),
            )

            sent = delivery_stats["sent"] or 1  # Avoid div by zero

            data = {
                "sent": delivery_stats["sent"] or 0,
                "delivery_rate": round(delivery_stats["delivered"] / sent * 100, 1),
                "bounce_rate": round(delivery_stats["bounced"] / sent * 100, 1),
                "open_rate": round(delivery_stats["opened"] / sent * 100, 1),
                "errors": list(
                    email_qs.filter(event_type="FAILED")
                    .values("event_type")
                    .annotate(count=Count("id"))
                    .order_by("-count")[:5]
                ),
            }
            cache.set(cache_key, data, 300)

        context.update(data)
        context.update(self.get_date_params())
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

            sent = c_emails.filter(event_type="SENT").count()
            opened = c_emails.filter(event_type="OPEN").count()
            plays = c_videos.filter(event_type="PLAY").count()

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
        context.update(self.get_date_params())
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

            sent = c_emails.filter(event_type="SENT").count()
            if sent == 0:
                continue

            delivered = c_emails.filter(event_type="SENT").count()  # No separate delivered state
            opened = c_emails.filter(event_type="OPEN").count()
            clicked = c_emails.filter(event_type="CLICK").count()
            plays = c_videos.filter(event_type="PLAY").count()
            comp = c_videos.filter(event_type="COMPLETE").count()
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
                plays=Count("id", filter=Q(event_type="PLAY")),
                q1=Count("id", filter=Q(event_type="PROGRESS", completion_percentage__gte=25)),
                q2=Count("id", filter=Q(event_type="PROGRESS", completion_percentage__gte=50)),
                q3=Count("id", filter=Q(event_type="PROGRESS", completion_percentage__gte=75)),
                comp=Count("id", filter=Q(event_type="COMPLETE")),
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
                delivered=Count("id", filter=Q(event_type="SENT")),
                bounced=Count("id", filter=Q(event_type="BOUNCED")),
                failed=Count("id", filter=Q(event_type="FAILED")),
            )
            data = {
                "labels": ["Delivered", "Bounced", "Failed"],
                "values": [stats["delivered"] or 0, stats["bounced"] or 0, stats["failed"] or 0],
            }
        else:
            return JsonResponse({"error": "Invalid chart type"}, status=400)

        return JsonResponse(data)


# =============================================================================
# INTERNAL REPORTS — superuser only
# =============================================================================


class SuperuserRequiredMixin(LoginRequiredMixin):
    """Allows only superusers. Redirects others to the analytics home."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_superuser:
            return redirect("analytics_home")
        return super().dispatch(request, *args, **kwargs)


class InternalRevenueReportView(SuperuserRequiredMixin, TemplateView):
    """Revenue & Invoicing Health — totals, collected vs outstanding, breakdown by service category."""

    template_name = "analytics/internal_revenue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models.functions import TruncMonth

        today = timezone.now().date()
        date_from = self.request.GET.get(
            "date_from", (today - timedelta(days=_DEFAULT_DAYS)).strftime(_DATE_FMT)
        )
        date_to = self.request.GET.get("date_to", today.strftime(_DATE_FMT))
        context["date_from"] = date_from
        context["date_to"] = date_to

        # Invoice aggregates filtered by issue_date
        qs = Invoice.objects.filter(issue_date__range=(date_from, date_to))
        totals = qs.aggregate(
            total_invoiced=Sum("amount"),
            collected=Sum("amount", filter=Q(status="Paid")),
            outstanding=Sum("amount", filter=Q(status__in=["Sent", "Draft"])),
            overdue=Sum("amount", filter=Q(status="Overdue")),
        )
        context["totals"] = {k: float(v or 0) for k, v in totals.items()}

        # Collection rate
        invoiced = float(totals["total_invoiced"] or 0)
        collected = float(totals["collected"] or 0)
        context["collection_rate"] = round(collected / invoiced * 100, 1) if invoiced > 0 else 0

        # Revenue by service category
        category_data = (
            InvoiceLineItem.objects.filter(invoice__issue_date__range=(date_from, date_to))
            .values("service__category")
            .annotate(total=Sum("total_amount"))
            .order_by("-total")
        )
        context["category_breakdown"] = [
            {"category": r["service__category"] or "other", "total": float(r["total"] or 0)}
            for r in category_data
        ]

        # Monthly revenue (last 12 months, always — not date-filtered)
        twelve_months_ago = today - timedelta(days=365)
        monthly = (
            Invoice.objects.filter(status="Paid", issue_date__gte=twelve_months_ago)
            .annotate(month=TruncMonth("issue_date"))
            .values("month")
            .annotate(revenue=Sum("amount"))
            .order_by("month")
        )
        context["monthly_revenue"] = [
            {"month": r["month"].strftime("%b %Y"), "revenue": float(r["revenue"] or 0)}
            for r in monthly
        ]

        # Per-charity table
        per_charity = (
            qs.values("charity__charity_name", "charity__id")
            .annotate(
                total=Sum("amount"),
                paid=Sum("amount", filter=Q(status="Paid")),
                outstanding=Sum("amount", filter=Q(status__in=["Sent", "Draft", "Overdue"])),
                invoice_count=Count("id"),
            )
            .order_by("-total")
        )
        context["per_charity"] = list(per_charity)
        return context


class InternalVolumeReportView(SuperuserRequiredMixin, TemplateView):
    """Platform Volume & Delivery Health — job totals, email event stats, VideoSendLog."""

    template_name = "analytics/internal_volume.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        date_from = self.request.GET.get(
            "date_from", (today - timedelta(days=_DEFAULT_DAYS)).strftime(_DATE_FMT)
        )
        date_to = self.request.GET.get("date_to", today.strftime(_DATE_FMT))
        context["date_from"] = date_from
        context["date_to"] = date_to

        # DonationJob totals
        job_qs = DonationJob.objects.filter(created_at__date__range=(date_from, date_to))
        job_totals = job_qs.aggregate(
            total=Count("id"),
            success=Count("id", filter=Q(status="success")),
            failed=Count("id", filter=Q(status="failed")),
            pending=Count("id", filter=Q(status="pending")),
        )
        context["job_totals"] = job_totals
        total = job_totals["total"] or 1
        context["success_rate"] = round((job_totals["success"] or 0) / total * 100, 1)

        # EmailEvent delivery breakdown
        email_qs = EmailEvent.objects.filter(timestamp__date__range=(date_from, date_to))
        email_totals = email_qs.aggregate(
            sent=Count("id", filter=Q(event_type="SENT")),
            delivered=Count("id", filter=Q(event_type="DELIVERED")),
            opened=Count("id", filter=Q(event_type="OPEN")),
            bounced=Count("id", filter=Q(event_type="BOUNCED")),
            failed=Count("id", filter=Q(event_type="FAILED")),
            complained=Count("id", filter=Q(event_type="COMPLAINED")),
        )
        context["email_totals"] = email_totals

        # VideoSendLog breakdown
        vsl_qs = VideoSendLog.objects.filter(created_at__date__range=(date_from, date_to))
        vsl_totals = vsl_qs.aggregate(
            total=Count("id"),
            sent=Count("id", filter=Q(status="SENT")),
            failed=Count("id", filter=Q(status="FAILED")),
        )
        context["vsl_totals"] = vsl_totals

        # Per-charity table
        per_charity = (
            job_qs.values("charity__charity_name")
            .annotate(
                total=Count("id"),
                success=Count("id", filter=Q(status="success")),
                failed=Count("id", filter=Q(status="failed")),
            )
            .order_by("-total")
        )
        context["per_charity"] = list(per_charity)

        # Daily job volume for chart (last N days)
        from django.db.models.functions import TruncDate as _TruncDate

        daily = (
            job_qs.annotate(day=_TruncDate("created_at"))
            .values("day")
            .annotate(total=Count("id"), success=Count("id", filter=Q(status="success")))
            .order_by("day")
        )
        context["daily_volume"] = [
            {"day": r["day"].strftime("%Y-%m-%d"), "total": r["total"], "success": r["success"]}
            for r in daily
        ]
        return context


class InternalAdoptionReportView(SuperuserRequiredMixin, TemplateView):
    """Team Adoption Rate per Client — members, roles, pending invites."""

    template_name = "analytics/internal_adoption.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Per-charity member breakdown (status and role counts)
        charities = (
            CharityMember.objects.values("charity__id", "charity__charity_name")
            .annotate(
                total_members=Count("id"),
                active=Count("id", filter=Q(status="ACTIVE")),
                pending=Count("id", filter=Q(status="PENDING")),
                admins=Count("id", filter=Q(role="Admin", status="ACTIVE")),
            )
            .order_by("-active")
        )
        rows = list(charities)
        max_active = max((r["active"] for r in rows), default=1) or 1
        for r in rows:
            r["adoption_score"] = round(r["active"] / max_active * 100)
        context["charities"] = rows
        context["total_members"] = sum(r["total_members"] for r in rows)
        context["total_active"] = sum(r["active"] for r in rows)
        return context


class InternalStorageReportView(SuperuserRequiredMixin, TemplateView):
    """Storage & Infrastructure Costs — R2 bucket usage by prefix."""

    template_name = "analytics/internal_storage.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .utils.cloudflare_stream import get_r2_storage_by_prefix

        storage = get_r2_storage_by_prefix()
        total_bytes = sum(v["bytes"] for v in storage.values())
        total_gb = round(total_bytes / 1_073_741_824, 3)
        context["storage_by_prefix"] = sorted(
            [{"prefix": k, **v} for k, v in storage.items()],
            key=lambda x: x["bytes"],
            reverse=True,
        )
        context["total_gb"] = total_gb
        context["total_cost_gbp"] = round(total_gb * 0.015, 4)
        context["configured"] = bool(storage)
        return context


# =============================================================================
# INTERNAL REPORTS — superuser only (continued)
# =============================================================================


# =============================================================================
# CHARITY / EXTERNAL REPORTS — charity-scoped
# =============================================================================


def _get_active_charity_or_none(request):
    """Return the active charity for scoping, or None for superusers with no context."""
    from .utils.access_control import get_active_charity

    return get_active_charity(request)


class CharityReportBaseView(LoginRequiredMixin, AnalyticsPermissionMixin, TemplateView):
    """Base for charity-scoped report views. Adds charity + date context."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charity = _get_active_charity_or_none(self.request)
        context["active_charity"] = charity
        today = timezone.now().date()
        context["date_from"] = self.request.GET.get(
            "date_from", (today - timedelta(days=_DEFAULT_DAYS)).strftime(_DATE_FMT)
        )
        context["date_to"] = self.request.GET.get("date_to", today.strftime(_DATE_FMT))
        if self.request.user.is_superuser:
            context["all_charities"] = Charity.objects.all().order_by("charity_name")
        return context


class CharityCampaignSummaryView(CharityReportBaseView):
    """Campaign Performance Summary — open rates, click rates, video play rates per campaign."""

    template_name = "analytics/charity_campaign_summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charity = context["active_charity"]
        date_from = context["date_from"]
        date_to = context["date_to"]

        campaigns = (
            Campaign.objects.filter(charity=charity).order_by("-created_at")
            if charity
            else Campaign.objects.none()
        )

        perf = []
        for camp in campaigns:
            stats, _ = CampaignStats.objects.get_or_create(campaign=camp)
            # Refresh if stale > 30 min
            if (timezone.now() - stats.last_updated).total_seconds() > 1800:
                stats.update_stats()

            email_qs = EmailEvent.objects.filter(
                campaign=camp, timestamp__date__range=(date_from, date_to)
            )
            sent = email_qs.filter(event_type="SENT").count()
            perf.append(
                {
                    "campaign": camp,
                    "sent": stats.total_sent,
                    "delivered": stats.total_sent - stats.total_failed,
                    "opened": stats.unique_opens,
                    "clicked": stats.total_clicks,
                    "video_plays": stats.total_video_views,
                    "open_rate": stats.open_rate,
                    "click_rate": stats.click_rate,
                    "video_rate": round(stats.total_video_views / stats.total_sent * 100, 1)
                    if stats.total_sent > 0
                    else 0,
                    "bounce_rate": stats.bounce_rate,
                    "completion_rate": stats.completion_rate,
                    "period_sent": sent,
                }
            )

        context["campaign_perf"] = perf
        return context


class CharityVideoEngagementView(CharityReportBaseView):
    """Advanced Video Engagement — Cloudflare Stream GraphQL minutes viewed + local fallback."""

    template_name = "analytics/charity_video_engagement.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charity = context["active_charity"]
        date_from = context["date_from"]
        date_to = context["date_to"]

        campaigns = (
            Campaign.objects.filter(charity=charity).exclude(cf_stream_video_id="")
            if charity
            else Campaign.objects.none()
        )
        video_uids = [c.cf_stream_video_id for c in campaigns if c.cf_stream_video_id]

        # Try Cloudflare Stream GraphQL for real watch-time data
        from .utils.cloudflare_stream import get_stream_video_analytics

        stream_data = get_stream_video_analytics(video_uids, date_from, date_to)

        rows = []
        for camp in campaigns:
            cf = stream_data.get(camp.cf_stream_video_id or "", {})
            # Supplement with local VideoEvent data
            local_qs = VideoEvent.objects.filter(
                campaign=camp, timestamp__date__range=(date_from, date_to)
            )
            local_plays = local_qs.filter(event_type="PLAY").count()
            local_completions = local_qs.filter(event_type="COMPLETE").count()
            local_avg_duration = (
                local_qs.filter(event_type="PLAY").aggregate(avg=Avg("watch_duration"))["avg"] or 0
            )
            rows.append(
                {
                    "campaign": camp,
                    "cf_plays": cf.get("plays", 0),
                    "cf_minutes": cf.get("minutes_viewed", 0.0),
                    "cf_avg_minutes": round(cf["minutes_viewed"] / cf["plays"], 2)
                    if cf.get("plays")
                    else 0,
                    "local_plays": local_plays,
                    "local_avg_duration": round(local_avg_duration, 1),
                    "local_completions": local_completions,
                    "completion_rate": round(local_completions / local_plays * 100, 1)
                    if local_plays > 0
                    else 0,
                    "source": "cloudflare" if cf else "local",
                }
            )
        context["video_rows"] = rows
        context["total_cf_minutes"] = round(sum(r["cf_minutes"] for r in rows), 2)
        context["cf_configured"] = bool(stream_data) or bool(video_uids)
        return context


class CharityDonorHeatmapView(CharityReportBaseView):
    """Donor Engagement Heatmap — top donors ranked by engagement score."""

    template_name = "analytics/charity_donor_heatmap.html"

    def get(self, request, *args, **kwargs):
        if request.GET.get("format") == "csv":
            return self._export_csv(request)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charity = context["active_charity"]
        date_from = context["date_from"]
        date_to = context["date_to"]

        donors = (
            DonationJob.objects.filter(
                charity=charity, status="success", created_at__date__range=(date_from, date_to)
            )
            .values("email", "donor_name")
            .annotate(
                total_views=Sum("real_views"),
                total_clicks=Sum("real_clicks"),
                campaigns=Count("campaign", distinct=True),
                jobs=Count("id"),
            )
            .annotate(
                # engagement_score = clicks*3 + views*1 + campaigns*2
            )
            .order_by("-total_clicks", "-total_views")[:100]
        )
        rows = []
        for d in donors:
            score = (
                (d["total_clicks"] or 0) * 3 + (d["total_views"] or 0) + (d["campaigns"] or 0) * 2
            )
            rows.append({**d, "engagement_score": score})
        rows.sort(key=lambda x: x["engagement_score"], reverse=True)
        context["donors"] = rows
        return context

    def _export_csv(self, request) -> HttpResponse:
        import csv as _csv

        charity = _get_active_charity_or_none(request)
        date_from = request.GET.get("date_from", "")
        date_to = request.GET.get("date_to", "")
        donors = (
            DonationJob.objects.filter(
                charity=charity, status="success", created_at__date__range=(date_from, date_to)
            )
            .values("email", "donor_name")
            .annotate(
                total_views=Sum("real_views"),
                total_clicks=Sum("real_clicks"),
                campaigns=Count("campaign", distinct=True),
            )
            .order_by("-total_clicks")[:500]
        )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=donor_heatmap.csv"
        writer = _csv.writer(response)
        writer.writerow(
            ["Email", "Donor Name", "Campaigns", "Total Views", "Total Clicks", "Engagement Score"]
        )
        for d in donors:
            score = (
                (d["total_clicks"] or 0) * 3 + (d["total_views"] or 0) + (d["campaigns"] or 0) * 2
            )
            writer.writerow(
                [
                    d["email"],
                    d["donor_name"],
                    d["campaigns"],
                    d["total_views"],
                    d["total_clicks"],
                    score,
                ]
            )
        return response


class CharityListHygieneView(CharityReportBaseView):
    """List Hygiene & Delivery Issues — bounces, unsubscribes, complaints, failed sends."""

    template_name = "analytics/charity_list_hygiene.html"

    def get(self, request, *args, **kwargs):
        if request.GET.get("format") == "csv":
            return self._export_csv(request)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charity = context["active_charity"]
        date_from = context["date_from"]
        date_to = context["date_to"]

        if charity:
            # Bounces from EmailEvent
            bounces = (
                EmailEvent.objects.filter(
                    campaign__charity=charity,
                    event_type="BOUNCED",
                    timestamp__date__range=(date_from, date_to),
                )
                .select_related("job", "campaign")
                .order_by("-timestamp")[:200]
            )
            # Resend-style failures
            failures = (
                EmailEvent.objects.filter(
                    campaign__charity=charity,
                    event_type__in=["FAILED", "SUPPRESSED"],
                    timestamp__date__range=(date_from, date_to),
                )
                .select_related("job", "campaign")
                .order_by("-timestamp")[:200]
            )
            # Spam complaints from Resend
            complaints = (
                EmailEvent.objects.filter(
                    campaign__charity=charity,
                    event_type="COMPLAINED",
                    timestamp__date__range=(date_from, date_to),
                )
                .select_related("job", "campaign")
                .order_by("-timestamp")[:200]
            )
            # Unsubscribes
            unsubs = UnsubscribedUser.objects.filter(
                charity=charity, created_at__date__range=(date_from, date_to)
            ).order_by("-created_at")[:200]
        else:
            bounces = failures = complaints = EmailEvent.objects.none()
            unsubs = UnsubscribedUser.objects.none()

        context.update(
            {
                "bounces": bounces,
                "failures": failures,
                "complaints": complaints,
                "unsubs": unsubs,
                "bounce_count": bounces.count() if hasattr(bounces, "count") else 0,
                "failure_count": failures.count() if hasattr(failures, "count") else 0,
                "complaint_count": complaints.count() if hasattr(complaints, "count") else 0,
                "unsub_count": unsubs.count() if hasattr(unsubs, "count") else 0,
            }
        )
        return context

    def _export_csv(self, request) -> HttpResponse:
        import csv as _csv

        charity = _get_active_charity_or_none(request)
        tab = request.GET.get("tab", "bounces")
        date_from = request.GET.get("date_from", "")
        date_to = request.GET.get("date_to", "")
        type_map = {"bounces": "BOUNCED", "failures": "FAILED", "complaints": "COMPLAINED"}
        event_type = type_map.get(tab, "BOUNCED")
        qs = (
            EmailEvent.objects.filter(
                campaign__charity=charity,
                event_type=event_type,
                timestamp__date__range=(date_from, date_to),
            )
            .select_related("job")
            .order_by("-timestamp")
        )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f"attachment; filename=list_hygiene_{tab}.csv"
        writer = _csv.writer(response)
        writer.writerow(["Email", "Donor Name", "Campaign", "Timestamp"])
        for ev in qs:
            email = ev.job.email if ev.job else ""
            name = ev.job.donor_name if ev.job else ""
            camp = ev.campaign.name if ev.campaign else ""
            writer.writerow([email, name, camp, ev.timestamp.strftime("%Y-%m-%d %H:%M")])
        return response


class CharityBillingSnapshotView(CharityReportBaseView):
    """Billing & Tier Usage Snapshot — recent invoices with line items + current period volume."""

    template_name = "analytics/charity_billing_snapshot.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        charity = context["active_charity"]

        if charity:
            invoices = (
                Invoice.objects.filter(charity=charity)
                .prefetch_related("line_items__service")
                .order_by("-issue_date")[:10]
            )
            # Current period: current month
            today = timezone.now().date()
            month_start = today.replace(day=1)
            period_jobs = DonationJob.objects.filter(
                charity=charity, created_at__date__gte=month_start
            )
            period_totals = period_jobs.aggregate(
                total=Count("id"),
                sent=Count("id", filter=Q(status="success")),
                failed=Count("id", filter=Q(status="failed")),
            )
            outstanding = Invoice.objects.filter(
                charity=charity, status__in=["Sent", "Overdue"]
            ).aggregate(total=Sum("amount"))
        else:
            invoices = Invoice.objects.none()
            period_totals = {"total": 0, "sent": 0, "failed": 0}
            outstanding = {"total": 0}

        context["invoices"] = invoices
        context["period_totals"] = period_totals
        context["outstanding_balance"] = float(outstanding.get("total") or 0)
        return context
