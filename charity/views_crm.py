from __future__ import annotations

"""
CRM integration views — Blackbaud Raiser's Edge NXT OAuth 2.0 flow.

    /crm/blackbaud/connect/   → redirect to Blackbaud authorization URL
    /crm/blackbaud/callback/  → handle authorization code, exchange for tokens
    /crm/blackbaud/disconnect/ → revoke stored tokens

All views require an authenticated user and an active charity.
"""

import logging
import secrets

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils.timezone import now

from charity.utils.access_control import get_active_charity
from charity.utils.crm_adapters.blackbaud import _save_tokens

logger = logging.getLogger(__name__)

_BLACKBAUD_AUTH_URL = "https://oauth2.sky.blackbaud.com/authorization"
_BLACKBAUD_TOKEN_URL = "https://oauth2.sky.blackbaud.com/token"

# Session key used to carry the CSRF state parameter across the OAuth redirect
_STATE_SESSION_KEY = "blackbaud_oauth_state"


@login_required(login_url="charity_login")
def blackbaud_connect(request):
    """
    Step 1 — redirect the charity admin to the Blackbaud authorization page.

    A cryptographically-random state token is stored in the session to
    protect against CSRF on the OAuth callback.
    """
    charity = get_active_charity(request)
    if not charity:
        messages.error(request, "No active charity selected.")
        return redirect("profile")

    if not settings.BLACKBAUD_CLIENT_ID:
        messages.error(request, "Blackbaud integration is not configured. Contact support.")
        return redirect("profile")

    state = secrets.token_urlsafe(32)
    request.session[_STATE_SESSION_KEY] = state

    params = {
        "client_id": settings.BLACKBAUD_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.BLACKBAUD_REDIRECT_URI,
        "state": state,
    }

    # Build the authorization URL manually without an extra dependency
    query = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"{_BLACKBAUD_AUTH_URL}?{query}"

    logger.info("Redirecting charity %s to Blackbaud authorization", charity.id)
    return redirect(auth_url)


@login_required(login_url="charity_login")
def blackbaud_callback(request):
    """
    Step 2 — Blackbaud redirects here with ?code=…&state=…

    Exchange the code for tokens, persist them on the Charity, and
    enable the integration.
    """
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
        return redirect("profile")

    error = request.GET.get("error")
    if error:
        description = request.GET.get("error_description", error)
        messages.error(request, f"Blackbaud authorization was denied: {description}")
        return redirect("profile")

    code = request.GET.get("code")
    if not code:
        messages.error(request, "No authorization code received from Blackbaud.")
        return redirect("profile")

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
        return redirect("profile")

    if resp.status_code != 200:
        logger.error(
            "Token exchange failed for charity %s: %s %s",
            charity.id,
            resp.status_code,
            resp.text[:200],
        )
        messages.error(request, "Blackbaud token exchange failed. Please try connecting again.")
        return redirect("profile")

    token_data = resp.json()
    _save_tokens(charity, token_data)
    charity.blackbaud_enabled = True
    charity.save(update_fields=["blackbaud_enabled"])

    logger.info("Blackbaud integration connected for charity %s", charity.id)
    messages.success(request, "Raiser's Edge NXT connected successfully. Donation sync is now active.")
    return redirect("profile")


@login_required(login_url="charity_login")
def blackbaud_disconnect(request):
    """
    Remove stored Blackbaud tokens and disable the integration for this charity.
    Only accepts POST to prevent accidental disconnection via navigating to the URL.
    """
    if request.method != "POST":
        return redirect("profile")

    charity = get_active_charity(request)
    if not charity:
        messages.error(request, "No active charity selected.")
        return redirect("profile")

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
    messages.success(request, "Raiser's Edge NXT has been disconnected.")
    return redirect("profile")
