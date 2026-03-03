"""
Reusable view mixins for access-control patterns used throughout the charity app.

These replace the duplicated inline ``if not request.user.is_superuser``
and ``get_active_charity(request)`` calls that previously appeared in every
view function.

Usage (function-based views keep using decorators; these are for CBVs)::

    class MyView(LoginRequiredMixin, ActiveCharityMixin, View):
        def get(self, request):
            charity = self.charity  # already resolved
            ...

For FBVs the utility function ``get_active_charity`` from
``charity.utils.access_control`` remains the canonical helper.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect

from .utils.access_control import get_active_charity

# ---------------------------------------------------------------------------
# ActiveCharityMixin
# ---------------------------------------------------------------------------


class ActiveCharityMixin:
    """
    Resolve the active :class:`Charity` for the current request and attach
    it as ``self.charity`` before the view handler runs.

    Redirects to the dashboard with an error message if no active charity
    can be resolved (e.g. a standard user with no membership).
    """

    charity = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)  # type: ignore[misc]
        self.charity = get_active_charity(request)

    def dispatch(self, request, *args, **kwargs):
        if self.charity is None and not request.user.is_superuser:
            messages.error(request, "No active client selected.")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SuperuserRequiredMixin
# ---------------------------------------------------------------------------


class SuperuserRequiredMixin(LoginRequiredMixin):
    """
    Restrict a view to Django superusers only.

    Non-superusers are redirected to the dashboard with an error message.
    Unauthenticated users are redirected to the login page (via
    :class:`~django.contrib.auth.mixins.LoginRequiredMixin`).
    """

    login_url = "charity_login"
    redirect_field_name = "next"

    def dispatch(self, request, *args, **kwargs):
        result = super().dispatch(request, *args, **kwargs)
        # If LoginRequiredMixin already short-circuited (not authenticated),
        # return its response directly.
        if not request.user.is_authenticated:
            return result
        if not request.user.is_superuser:
            messages.error(request, "Unauthorized action.")
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CharityMemberRequiredMixin
# ---------------------------------------------------------------------------


class CharityMemberRequiredMixin(LoginRequiredMixin, ActiveCharityMixin):
    """
    Restrict a view to authenticated users who are members of the active
    charity (or superusers who have selected an active charity context).

    Combines :class:`LoginRequiredMixin` and :class:`ActiveCharityMixin`.
    Redirects unauthenticated users to the login page and non-members to
    the dashboard.
    """

    login_url = "charity_login"
    redirect_field_name = "next"

    def dispatch(self, request, *args, **kwargs):
        # Let LoginRequiredMixin handle unauthenticated users first.
        response = super().dispatch(request, *args, **kwargs)

        if not request.user.is_authenticated:
            return response

        # Superusers bypass membership check.
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

        # Verify active membership.
        from .models import CharityMember

        if self.charity and not CharityMember.objects.filter(
            charity=self.charity, user=request.user, status="ACTIVE"
        ).exists():
            messages.error(request, "You are not a member of the selected organisation.")
            return redirect("dashboard")

        return response
