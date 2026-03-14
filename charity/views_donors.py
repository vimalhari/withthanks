from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Max, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .models import Donation, Donor, VideoSendLog
from .utils.access_control import get_active_charity


def _get_active_charity_or_redirect(request):
    charity = get_active_charity(request)
    if charity is not None:
        return charity, None

    messages.warning(request, "Select a charity context before viewing donor records.")
    return None, redirect("dashboard")


def _donor_prefetches(charity):
    return [
        Prefetch(
            "donations",
            queryset=Donation.objects.filter(charity=charity).order_by("-donated_at", "-id"),
        ),
        Prefetch(
            "video_send_logs",
            queryset=(
                VideoSendLog.objects.filter(charity=charity)
                .select_related("campaign", "donation")
                .order_by("-created_at", "-id")
            ),
        ),
    ]


def _attach_donor_metrics(donor):
    donations = list(donor.donations.all())
    send_logs = list(donor.video_send_logs.all())

    donor.donation_count = len(donations)
    donor.total_donated = sum((donation.amount for donation in donations), Decimal("0.00"))
    donor.first_donation_at = donations[-1].donated_at if donations else None
    donor.last_donation_at = donations[0].donated_at if donations else None
    donor.send_count = len(send_logs)
    donor.sent_count = sum(1 for log in send_logs if log.status == VideoSendLog.Status.SENT)
    donor.failed_send_count = sum(
        1 for log in send_logs if log.status == VideoSendLog.Status.FAILED
    )
    donor.last_send_at = send_logs[0].sent_at if send_logs else None
    donor.latest_send = send_logs[0] if send_logs else None


@login_required(login_url="charity_login")
def donors_view(request):
    charity, redirect_response = _get_active_charity_or_redirect(request)
    if redirect_response is not None:
        return redirect_response

    search_query = request.GET.get("q", "").strip()
    source_filter = request.GET.get("source", "").strip().upper()

    donors_qs = Donor.objects.filter(charity=charity).prefetch_related(*_donor_prefetches(charity))
    if search_query:
        donors_qs = donors_qs.filter(
            Q(full_name__icontains=search_query) | Q(email__icontains=search_query)
        )
    if source_filter in {"API", "CSV"}:
        donors_qs = donors_qs.filter(donations__source=source_filter).distinct()

    donors_qs = donors_qs.annotate(last_donation_sort=Max("donations__donated_at")).order_by(
        "-last_donation_sort", "-created_at"
    )

    filtered_donations = Donation.objects.filter(charity=charity, donor__in=donors_qs)
    filtered_logs = VideoSendLog.objects.filter(charity=charity, donor__in=donors_qs)
    stats = {
        "total_donors": donors_qs.count(),
        "total_donations": filtered_donations.count(),
        "total_revenue": filtered_donations.aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00"),
        "successful_sends": filtered_logs.filter(status=VideoSendLog.Status.SENT).count(),
    }

    paginator = Paginator(donors_qs, 25)
    donors_page = paginator.get_page(request.GET.get("page"))
    for donor in donors_page.object_list:
        _attach_donor_metrics(donor)

    return render(
        request,
        "donors.html",
        {
            "current_charity": charity,
            "donors": donors_page,
            "has_filters": bool(search_query or source_filter),
            "search_query": search_query,
            "source_filter": source_filter,
            "stats": stats,
        },
    )


@login_required(login_url="charity_login")
def donor_detail_view(request, donor_id):
    charity, redirect_response = _get_active_charity_or_redirect(request)
    if redirect_response is not None:
        return redirect_response

    donor = get_object_or_404(
        Donor.objects.filter(charity=charity).prefetch_related(*_donor_prefetches(charity)),
        id=donor_id,
    )
    _attach_donor_metrics(donor)

    donations = list(donor.donations.all())
    send_logs = list(donor.video_send_logs.all())
    donations_page = Paginator(donations, 15).get_page(request.GET.get("donations_page"))
    sends_page = Paginator(send_logs, 10).get_page(request.GET.get("sends_page"))

    stats = {
        "average_donation": (
            donor.total_donated / donor.donation_count if donor.donation_count else Decimal("0.00")
        ),
        "successful_sends": donor.sent_count,
        "failed_sends": donor.failed_send_count,
    }

    return render(
        request,
        "donor_detail.html",
        {
            "current_charity": charity,
            "donations": donations_page,
            "donor": donor,
            "send_logs": sends_page,
            "stats": stats,
        },
    )


@login_required(login_url="charity_login")
def donations_view(request):
    charity, redirect_response = _get_active_charity_or_redirect(request)
    if redirect_response is not None:
        return redirect_response

    search_query = request.GET.get("q", "").strip()
    source_filter = request.GET.get("source", "").strip().upper()
    campaign_type_filter = request.GET.get("campaign_type", "").strip().upper()

    donations_qs = (
        Donation.objects.filter(charity=charity, donor__charity=charity)
        .select_related("donor")
        .prefetch_related(
            Prefetch(
                "video_send_logs",
                queryset=(
                    VideoSendLog.objects.filter(charity=charity)
                    .select_related("campaign")
                    .order_by("-created_at", "-id")
                ),
            )
        )
    )
    if search_query:
        donations_qs = donations_qs.filter(
            Q(donor__full_name__icontains=search_query) | Q(donor__email__icontains=search_query)
        )
    if source_filter in {"API", "CSV"}:
        donations_qs = donations_qs.filter(source=source_filter)
    if campaign_type_filter:
        donations_qs = donations_qs.filter(campaign_type=campaign_type_filter)

    donations_qs = donations_qs.order_by("-donated_at", "-id")
    stats = {
        "total_donations": donations_qs.count(),
        "total_amount": donations_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "api_imports": donations_qs.filter(source="API").count(),
        "csv_imports": donations_qs.filter(source="CSV").count(),
    }

    paginator = Paginator(donations_qs, 25)
    donations_page = paginator.get_page(request.GET.get("page"))
    for donation in donations_page.object_list:
        logs = list(donation.video_send_logs.all())
        donation.send_count = len(logs)
        donation.latest_send = logs[0] if logs else None

    return render(
        request,
        "donations.html",
        {
            "campaign_type_filter": campaign_type_filter,
            "current_charity": charity,
            "donations": donations_page,
            "has_filters": bool(search_query or source_filter or campaign_type_filter),
            "search_query": search_query,
            "source_filter": source_filter,
            "stats": stats,
        },
    )
