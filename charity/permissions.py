"""
DRF permission classes for the charity app API.

These replace the plain ``IsAuthenticated`` checks that were previously
used inline in ``charity/api/views.py``.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated

from charity.models import CharityMember


class IsCharityMember(IsAuthenticated):
    """
    Allow access to authenticated users who are active members of at least
    one charity.  Superusers always pass.
    """

    message = "You must be an active charity member to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser:
            return True
        return CharityMember.objects.filter(user=request.user, status="ACTIVE").exists()


class IsCharityAdmin(IsAuthenticated):
    """
    Allow access to authenticated users who hold an **Admin** role in at
    least one charity.  Superusers always pass.
    """

    message = "You must be a charity Admin to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser:
            return True
        return CharityMember.objects.filter(
            user=request.user, role="Admin", status="ACTIVE"
        ).exists()
