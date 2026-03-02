from charity.models import Charity, CharityMember


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

    # Standard User
    # Try to get from CharityMember (The new source of truth)
    membership = CharityMember.objects.filter(user=user).first()
    if membership:
        return membership.charity

    # Validation Fallback for legacy (if we still had onetoone, but we are moving away)
    # This is just in case migration isn't perfect yet
    if hasattr(user, "charity"):
        return user.charity

    return None
