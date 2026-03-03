---
description: "Generate a test class for WithThanks with multi-tenant isolation"
---

# New Test Class

Create a test class following WithThanks testing conventions.

## Requirements
- Use `django.test.TestCase` as base class.
- Always set up at least 2 charities to verify multi-tenant isolation.
- Mock all external APIs (ElevenLabs, Resend, Cloudflare, Stripe).
- Use `@override_settings` for storage backend.
- Test both positive (authorized access) and negative (unauthorized/cross-tenant) cases.

## Template
```python
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from charity.models import Campaign, Charity, CharityMember, DonationBatch, DonationJob


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
)
class ${1:FeatureName}Tests(TestCase):
    """Tests for ${2:feature description}."""

    def setUp(self):
        # Charity A (primary test subject)
        self.user_a = User.objects.create_user(username="user_a", password="testpass123")
        self.charity_a = Charity.objects.create(
            client_name="Charity A",
            contact_email="a@test.com",
            organization_name="Org A",
        )
        CharityMember.objects.create(
            charity=self.charity_a, user=self.user_a, role="Admin", status="ACTIVE"
        )

        # Charity B (isolation verification)
        self.user_b = User.objects.create_user(username="user_b", password="testpass123")
        self.charity_b = Charity.objects.create(
            client_name="Charity B",
            contact_email="b@test.com",
            organization_name="Org B",
        )
        CharityMember.objects.create(
            charity=self.charity_b, user=self.user_b, role="Admin", status="ACTIVE"
        )

        self.client = Client()

    def test_${3:feature}_authorized(self):
        """Authenticated user with correct charity can access the feature."""
        self.client.login(username="user_a", password="testpass123")
        response = self.client.get(reverse("${4:url_name}"))
        self.assertEqual(response.status_code, 200)

    def test_${3}_unauthenticated_redirects(self):
        """Unauthenticated user is redirected to login."""
        response = self.client.get(reverse("${4}"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_${3}_tenant_isolation(self):
        """User A cannot see Charity B's data."""
        self.client.login(username="user_a", password="testpass123")
        response = self.client.get(reverse("${4}"))
        self.assertNotContains(response, "Charity B")
```

## After Creating
1. Run tests: `make test` or `uv run python manage.py test charity`.
2. Verify all assertions pass.
