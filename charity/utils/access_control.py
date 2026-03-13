from __future__ import annotations

from charity.models import Campaign, Charity, CharityMember, DonationJob


def get_active_memberships(user):
    if not user.is_authenticated:
        return CharityMember.objects.none()
    return CharityMember.objects.filter(user=user, status="ACTIVE").select_related("charity")


def get_accessible_charities(user):
    if not user.is_authenticated:
        return Charity.objects.none()
    if user.is_superuser:
        return Charity.objects.all()
    return Charity.objects.filter(
        charitymember__user=user,
        charitymember__status="ACTIVE",
    ).distinct()


def get_accessible_campaigns(user):
    if not user.is_authenticated:
        return Campaign.objects.none()
    if user.is_superuser:
        return Campaign.objects.all()
    return Campaign.objects.filter(
        client__charitymember__user=user,
        client__charitymember__status="ACTIVE",
    ).distinct()


def get_accessible_jobs(user):
    if not user.is_authenticated:
        return DonationJob.objects.none()
    if user.is_superuser:
        return DonationJob.objects.all()
    return DonationJob.objects.filter(
        charity__charitymember__user=user,
        charity__charitymember__status="ACTIVE",
    ).distinct()


def get_authorized_charity(user, charity_id):
    if charity_id in (None, ""):
        return None
    return get_accessible_charities(user).filter(id=charity_id).first()


def get_authorized_campaign(user, campaign_id):
    if campaign_id in (None, ""):
        return None
    return get_accessible_campaigns(user).select_related("client").filter(id=campaign_id).first()


def get_active_charity(request):
    """
    Retrieve the active charity for the current request.

    Logic:
    1. If Superuser:
       - Check session for 'active_charity_id'.
       - If found, return that Charity (if exists).
       - If not found, return None (Dashboard should show global view or prompt to select).

    2. If Standard User:
       - Return their associated Charity via CharityMember.
       - If multiple memberships, return the first one (or handle selection later).
       - If no membership, return None.
    """
    user = request.user
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        charity_id = request.session.get("active_charity_id")
        if charity_id:
            try:
                return Charity.objects.get(id=charity_id)
            except Charity.DoesNotExist:
                # Invalid ID in session, clear it
                request.session.pop("active_charity_id", None)
                return None
        return None  # Superuser in "Global View" mode

    # Standard User — source of truth is ACTIVE CharityMember rows.
    membership = get_active_memberships(user).first()
    if membership:
        return membership.charity

    return None
