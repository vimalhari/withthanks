---
description: Testing patterns and conventions for the WithThanks Django project
applyTo: "charity/tests*.py"
---

# Testing Instructions

## Test Framework
- Use `django.test.TestCase` as the base class for all tests.
- Use `django.test.Client` for HTTP request testing.
- Use `unittest.mock.patch` and `unittest.mock.MagicMock` for mocking external APIs.

## Test File Organization
- `charity/tests.py` — core model and view tests (multi-tenancy isolation)
- `charity/tests_multi_tenancy.py` — additional multi-tenancy tests

## Test Setup Pattern
```python
from django.contrib.auth.models import User
from django.test import Client, TestCase
from charity.models import Campaign, Charity, CharityMember, DonationBatch, DonationJob

class MyFeatureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.charity = Charity.objects.create(
            client_name="Test Charity",
            contact_email="test@example.com",
            organization_name="Test Org",
        )
        CharityMember.objects.create(
            charity=self.charity, user=self.user, role="Admin", status="ACTIVE"
        )
        self.client = Client()
        self.client.login(username="testuser", password="password")
```

## Multi-Tenancy Testing
- ALWAYS create at least 2 charities and verify data isolation.
- Assert that Charity A's views never expose Charity B's data.
- Test both positive (own data visible) and negative (other data hidden) cases.

## Mocking External APIs
- Always mock these external services in tests:
  - ElevenLabs TTS API → `charity.utils.voiceover_utils`
  - Resend email API → `charity.utils.resend_utils`
  - Cloudflare Stream → `charity.utils.cloudflare_stream`
- Use `@override_settings` for storage backend overrides:
  ```python
  @override_settings(
      STORAGES={
          "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
          "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
      }
  )
  ```

## API Tests
```python
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

class APITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="apiuser", password="password")
        self.api_client = APIClient()
        token = RefreshToken.for_user(self.user)
        self.api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
```

## Running Tests
- `make test` — run all tests
- `make test-verbose` — run with verbosity=2
- `uv run python manage.py test charity.tests.SpecificTestClass` — run specific test class

## Test Assertions
- Use `self.assertEqual`, `self.assertTrue`, `self.assertContains`, `self.assertNotContains`.
- For response codes: `self.assertEqual(response.status_code, 200)`.
- For redirects: `self.assertRedirects(response, expected_url)`.
- For JSON API responses: `response.json()` to parse body.

## What to Test
- Multi-tenant data isolation (highest priority)
- Permission enforcement (logged-in, charity member, admin)
- CSV upload parsing and validation
- Invoice lifecycle (create → send → mark-paid / void)
- Celery task execution (mock the heavy external calls)
- API serializer validation
