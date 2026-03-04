from __future__ import annotations

"""
CRM integration views — Blackbaud Raiser's Edge NXT OAuth 2.0 flow.

    /crm/blackbaud/connect/              → charity portal: connect using active charity
    /admin-crm/blackbaud/<id>/connect/   → superuser admin: connect a specific charity by id
    /crm/blackbaud/callback/             → handle authorization code, exchange for tokens
    /crm/blackbaud/disconnect/           → revoke stored tokens (portal)
    /admin-crm/blackbaud/<id>/disconnect/ → revoke stored tokens (admin)

Superuser-initiated flows store the target charity_id in the session so the callback
knows which charity to connect, then redirect back to the Django admin change page.
"""

import logging
import secrets

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.timezone import now

from charity.models import Charity
from charity.utils.access_control import get_active_charity
from charity.utils.crm_adapters.blackbaud import _save_tokens

logger = logging.getLogger(__name__)

_BLACKBAUD_AUTH_URL = "https://oauth2.sky.blackbaud.com/authorization"
_BLACKBAUD_TOKEN_URL = "https://oauth2.sky.blackbaud.com/token"

# Session keys used across the OAuth redirect
_STATE_SESSION_KEY = "blackbaud_oauth_state"
_CHARITY_ID_SESSION_KEY = "blackbaud_oauth_charity_id"
_ADMIN_ORIGIN_SESSION_KEY = "blackbaud_oauth_admin_origin"


@login_required(login_url="charity_login")
def blackbaud_connect(request):
    """
    Step 1 (portal) — redirect to Blackbaud authorization using the active charity.

    A cryptographically-random state token is stored in the session to
    protect against CSRF on the OAuth callback.
    """
    charity = get_active_charity(request)
    if not charity:
        messages.error(request, "No active charity selected.")
        return redirect("profile")
    return _initiate_blackbaud_oauth(request, charity, admin_origin=False)


@login_required(login_url="charity_login")
def blackbaud_admin_connect(request, charity_id: int):
    """
    Step 1 (admin) — superuser initiates the OAuth flow for any charity directly
    from the Django admin Charity change page.
    """
    if not request.user.is_superuser:
        messages.error(request, "Permission denied.")
        return redirect("admin:charity_charity_changelist")
    charity = get_object_or_404(Charity, id=charity_id)
    return _initiate_blackbaud_oauth(request, charity, admin_origin=True)


def _initiate_blackbaud_oauth(request, charity, *, admin_origin: bool):
    """Shared logic: build the Blackbaud authorization URL and redirect."""
    if not settings.BLACKBAUD_CLIENT_ID:
        messages.error(request, "Blackbaud integration is not configured. Contact support.")
        return _post_connect_redirect(request, charity, admin_origin)

    state = secrets.token_urlsafe(32)
    request.session[_STATE_SESSION_KEY] = state
    request.session[_CHARITY_ID_SESSION_KEY] = charity.id
    request.session[_ADMIN_ORIGIN_SESSION_KEY] = admin_origin

    params = {
        "client_id": settings.BLACKBAUD_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.BLACKBAUD_REDIRECT_URI,
        "state": state,
    }

    query = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"{_BLACKBAUD_AUTH_URL}?{query}"

    logger.info(
        "Redirecting charity %s to Blackbaud authorization (admin_origin=%s)",
        charity.id,
        admin_origin,
    )
    return redirect(auth_url)


@login_required(login_url="charity_login")
def blackbaud_callback(request):
    """
    Step 2 — Blackbaud redirects here with ?code=…&state=…

    Works for both portal-initiated and admin-initiated flows.
    Admin flows redirect back to the Charity change page after connecting.
    """
    # Retrieve which charity this OAuth flow is for (set by _initiate_blackbaud_oauth)
    charity_id = request.session.pop(_CHARITY_ID_SESSION_KEY, None)
    admin_origin = request.session.pop(_ADMIN_ORIGIN_SESSION_KEY, False)

    if charity_id:
        try:
            charity = Charity.objects.get(id=charity_id)
        except Charity.DoesNotExist:
            messages.error(request, "Charity not found.")
            return redirect("admin:charity_charity_changelist" if admin_origin else "profile")
    else:
        # Fallback: portal flow without explicit charity_id in session
        charity = get_active_charity(request)
        if not charity:
            messages.error(request, "No active charity selected.")
            return redirect("profile")

    # CSRF state check
    expected_state = request.session.pop(_STATE_SESSION_KEY, None)
    received_state = request.GET.get("state")
    if not expected_state or expected_state != received_state:
        logger.warning(
            "Blackbaud OAuth state mismatch for charity %s (expected %s, got %s)",
            charity.id,
            expected_state,
            received_state,
        )
        messages.error(request, "Authorization failed: invalid state. Please try again.")
        return _post_connect_redirect(request, charity, admin_origin)

    error = request.GET.get("error")
    if error:
        description = request.GET.get("error_description", error)
        messages.error(request, f"Blackbaud authorization was denied: {description}")
        return _post_connect_redirect(request, charity, admin_origin)

    code = request.GET.get("code")
    if not code:
        messages.error(request, "No authorization code received from Blackbaud.")
        return _post_connect_redirect(request, charity, admin_origin)

    # Exchange code for tokens
    try:
        resp = requests.post(
            _BLACKBAUD_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.BLACKBAUD_REDIRECT_URI,
                "client_id": settings.BLACKBAUD_CLIENT_ID,
                "client_secret": settings.BLACKBAUD_CLIENT_SECRET,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.exception("Token exchange request failed for charity %s", charity.id)
        messages.error(request, f"Could not reach Blackbaud: {exc}")
        return _post_connect_redirect(request, charity, admin_origin)

    if resp.status_code != 200:
        logger.error(
            "Token exchange failed for charity %s: %s %s",
            charity.id,
            resp.status_code,
            resp.text[:200],
        )
        messages.error(request, "Blackbaud token exchange failed. Please try connecting again.")
        return _post_connect_redirect(request, charity, admin_origin)

    token_data = resp.json()
    _save_tokens(charity, token_data)
    charity.blackbaud_enabled = True
    charity.save(update_fields=["blackbaud_enabled"])

    logger.info("Blackbaud integration connected for charity %s (admin_origin=%s)", charity.id, admin_origin)
    messages.success(
        request,
        f"Raiser's Edge NXT connected for {charity.client_name}. Donation sync is now active.",
    )
    return _post_connect_redirect(request, charity, admin_origin)


@login_required(login_url="charity_login")
def blackbaud_disconnect(request):
    """
    Remove stored Blackbaud tokens and disable the integration (portal flow).
    Only accepts POST to prevent accidental disconnection via navigating to the URL.
    """
    if request.method != "POST":
        return redirect("profile")

    charity = get_active_charity(request)
    if not charity:
        messages.error(request, "No active charity selected.")
        return redirect("profile")

    _clear_blackbaud_tokens(charity)
    messages.success(request, "Raiser's Edge NXT has been disconnected.")
    return redirect("profile")


@login_required(login_url="charity_login")
def blackbaud_admin_disconnect(request, charity_id: int):
    """
    Remove stored Blackbaud tokens for a specific charity (admin flow).
    Only accepts POST.
    """
    if not request.user.is_superuser:
        messages.error(request, "Permission denied.")
        return redirect("admin:charity_charity_changelist")

    if request.method != "POST":
        return redirect("admin:charity_charity_change", charity_id)

    charity = get_object_or_404(Charity, id=charity_id)
    _clear_blackbaud_tokens(charity)
    messages.success(request, f"Raiser's Edge NXT disconnected for {charity.client_name}.")
    return redirect("admin:charity_charity_change", charity_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clear_blackbaud_tokens(charity) -> None:
    """Zero out all Blackbaud OAuth tokens and disable the integration."""
    charity.blackbaud_enabled = False
    charity.blackbaud_access_token = None
    charity.blackbaud_refresh_token = None
    charity.blackbaud_token_expires_at = None
    charity.blackbaud_last_synced_at = None
    charity.blackbaud_environment_id = None
    charity.save(
        update_fields=[
            "blackbaud_enabled",
            "blackbaud_access_token",
            "blackbaud_refresh_token",
            "blackbaud_token_expires_at",
            "blackbaud_last_synced_at",
            "blackbaud_environment_id",
        ]
    )
    logger.info("Blackbaud integration disconnected for charity %s", charity.id)


def _post_connect_redirect(request, charity, admin_origin: bool):
    """Redirect to the right place after connect/disconnect/error."""
    if admin_origin:
        return redirect("admin:charity_charity_change", charity.id)
    return redirect("profile")
