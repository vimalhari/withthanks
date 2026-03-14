from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from .models import Charity, Invoice
from .utils.access_control import get_active_charity
from .views_analytics import AnalyticsPermissionMixin


class RevenueIntelligenceAPI(LoginRequiredMixin, AnalyticsPermissionMixin, View):
    """
    Provides data for the Revenue Intelligence Dashboard.
    """

    def get(self, request):
        charity = get_active_charity(request)
        if not charity and not request.user.is_superuser:
            return JsonResponse({"error": "Unauthorized"}, status=403)

        # Base queryset
        if request.user.is_superuser and not charity:
            invoices = Invoice.objects.all()
        else:
            invoices = Invoice.objects.filter(charity=charity)

        now = timezone.now()
        this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)

        # KPI Calculations
        # This Month Revenue
        this_month_invoices = invoices.filter(issue_date__gte=this_month_start)
        this_month_revenue = this_month_invoices.aggregate(total=Sum("amount"))["total"] or 0

        # Last Month Revenue for Growth
        last_month_invoices = invoices.filter(
            issue_date__gte=last_month_start, issue_date__lt=this_month_start
        )
        last_month_revenue = last_month_invoices.aggregate(total=Sum("amount"))["total"] or 0
        revenue_growth = 0
        if last_month_revenue > 0:
            revenue_growth = ((this_month_revenue - last_month_revenue) / last_month_revenue) * 100

        # Paid This Month
        paid_this_month = (
            invoices.filter(status="Paid", paid_at__gte=this_month_start).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

        # Pending & Overdue
        pending_amount = (
            invoices.filter(status__in=["Sent", "Draft"]).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        overdue_amount = (
            invoices.filter(status="Overdue").aggregate(total=Sum("amount"))["total"] or 0
        )

        # Collection Rate (This Month)
        total_billed = this_month_revenue
        collection_rate = 0
        if total_billed > 0:
            collection_rate = (paid_this_month / total_billed) * 100

        # Efficiency Metrics
        paid_invoices = invoices.filter(
            status="Paid", paid_at__isnull=False, issue_date__isnull=False
        )
        avg_days_to_pay = paid_invoices.annotate(
            days=F("paid_at__date") - F("issue_date")
        ).aggregate(avg=Avg("days"))["avg"]

        avg_collection_days = avg_days_to_pay.days if avg_days_to_pay else 0

        # Invoice conversion rate (Sent -> Paid)
        total_sent = invoices.filter(status__in=["Sent", "Paid", "Overdue"]).count()
        total_paid = invoices.filter(status="Paid").count()
        conversion_rate = (total_paid / total_sent * 100) if total_sent > 0 else 0

        # Avg Invoice Value
        avg_invoice_value = invoices.aggregate(avg=Avg("amount"))["avg"] or 0

        # Monthly Chart Data
        monthly_data = list(
            invoices.annotate(month=TruncMonth("issue_date"))
            .values("month")
            .annotate(revenue=Sum("amount"), paid=Sum("amount", filter=Q(status="Paid")))
            .order_by("month")
        )

        chart_months = [d["month"].strftime("%b %Y") for d in monthly_data[-12:]]
        chart_revenue = [float(d["revenue"] or 0) for d in monthly_data[-12:]]
        chart_paid = [float(d["paid"] or 0) for d in monthly_data[-12:]]

        # Growth Rate Line (Rolling growth)
        growth_line = []
        for i, curr in enumerate(chart_revenue):
            if i == 0:
                growth_line.append(0)
            else:
                prev = chart_revenue[i - 1]
                growth = ((curr - prev) / prev * 100) if prev > 0 else 0
                growth_line.append(round(growth, 1))

        # Client Analytics Table
        client_stats = (
            Charity.objects.annotate(
                total_invoiced=Sum("invoices__amount"),
                total_paid=Sum("invoices__amount", filter=Q(invoices__status="Paid")),
                avg_days=Avg(
                    F("invoices__paid_at__date") - F("invoices__issue_date"),
                    filter=Q(invoices__status="Paid"),
                ),
            )
            .filter(total_invoiced__gt=0)
            .order_by("-total_invoiced")
        )

        clients_list = []
        for c in client_stats:
            clients_list.append(
                {
                    "name": c.charity_name,
                    "total_billed": float(c.total_invoiced or 0),
                    "outstanding": float((c.total_invoiced or 0) - (c.total_paid or 0)),
                    "avg_pay_days": c.avg_days.days if c.avg_days else "-",
                    "status": "Good" if (c.avg_days.days if c.avg_days else 0) < 15 else "Slow",
                }
            )

        return JsonResponse(
            {
                "kpis": {
                    "this_month_billed": float(this_month_revenue),
                    "paid_this_month": float(paid_this_month),
                    "pending_amount": float(pending_amount),
                    "overdue_amount": float(overdue_amount),
                    "collection_rate": f"{round(collection_rate, 1)}%",
                    "avg_invoice_value": float(avg_invoice_value),
                    "revenue_growth": f"{round(revenue_growth, 1)}%",
                },
                "efficiency": {
                    "avg_collection_time": f"{avg_collection_days} days",
                    "conversion_rate": f"{round(conversion_rate, 1)}%",
                    "efficiency_score": f"{round(100 - (avg_collection_days / 30 * 100), 1) if avg_collection_days < 30 else 0}%",
                },
                "charts": {
                    "labels": chart_months,
                    "revenue": chart_revenue,
                    "paid": chart_paid,
                    "growth": growth_line,
                    "status_pie": [
                        invoices.filter(status="Paid").count(),
                        invoices.filter(status="Sent").count(),
                        invoices.filter(status="Overdue").count(),
                        invoices.filter(status="Draft").count(),
                    ],
                },
                "clients": clients_list[:10],
            }
        )
