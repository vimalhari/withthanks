"""
Tests for the WithThanks charity app.

Covers: models, serializers, API views, and the video dispatch service.
External services (ElevenLabs, FFmpeg, Cloudflare, Resend) are fully mocked so
the test suite can run in CI without any credentials or system deps.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from charity.models import Campaign, Charity, Donation, Donor, TextTemplate, VideoSendLog, VideoTemplate
from charity.services.video_dispatch import (
    _default_gratitude_text,
    _default_personalized_text,
    _render_template,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_charity(name: str = "Test Charity") -> Charity:
    user = User.objects.create_user(username=name.lower().replace(" ", "_"), password="pass")
    return Charity.objects.create(name=name, user=user)


def make_campaign(
    charity: Charity,
    *,
    campaign_type: str = Campaign.CampaignType.THANK_YOU,
    video_mode: str = Campaign.VideoMode.PERSONALIZED,
    is_active: bool = True,
) -> Campaign:
    return Campaign.objects.create(
        charity=charity,
        name=f"{charity.name} Campaign",
        campaign_type=campaign_type,
        video_mode=video_mode,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class CharityModelTest(TestCase):
    def test_str(self) -> None:
        charity = make_charity("Green Earth")
        self.assertEqual(str(charity), "Green Earth")


class DonorModelTest(TestCase):
    def test_unique_charity_email(self) -> None:
        charity = make_charity()
        Donor.objects.create(charity=charity, email="a@b.com")
        with self.assertRaises(Exception):
            Donor.objects.create(charity=charity, email="a@b.com")

    def test_str(self) -> None:
        charity = make_charity()
        donor = Donor.objects.create(charity=charity, email="donor@test.com")
        self.assertIn("donor@test.com", str(donor))


class DonationModelTest(TestCase):
    def setUp(self) -> None:
        self.charity = make_charity()
        self.donor = Donor.objects.create(charity=self.charity, email="d@test.com")

    def test_str(self) -> None:
        donation = Donation.objects.create(
            donor=self.donor, charity=self.charity, amount=Decimal("50.00")
        )
        self.assertIn("50.00", str(donation))


class CampaignModelTest(TestCase):
    def test_str(self) -> None:
        charity = make_charity()
        campaign = make_campaign(charity)
        self.assertIn(charity.name, str(campaign))


class VideoSendLogModelTest(TestCase):
    def test_str(self) -> None:
        charity = make_charity()
        donor = Donor.objects.create(charity=charity, email="vsl@test.com")
        donation = Donation.objects.create(donor=donor, charity=charity, amount=Decimal("10"))
        log = VideoSendLog.objects.create(
            charity=charity,
            donor=donor,
            donation=donation,
            campaign_type=Campaign.CampaignType.THANK_YOU,
            send_kind=VideoSendLog.SendKind.PERSONALIZED,
            status=VideoSendLog.Status.SENT,
            recipient_email="vsl@test.com",
            video_file="/tmp/video.mp4",
        )
        self.assertIn("SENT", str(log))


# ---------------------------------------------------------------------------
# Service / helper unit tests (no I/O)
# ---------------------------------------------------------------------------

class RenderTemplateTest(TestCase):
    def test_replaces_placeholders(self) -> None:
        result = _render_template(
            "Hi {{ donor_name }}, you gave {{ donation_amount }}.",
            {"donor_name": "Alice", "donation_amount": "50"},
        )
        self.assertEqual(result, "Hi Alice, you gave 50.")

    def test_missing_key_replaced_with_empty(self) -> None:
        result = _render_template("Hello {{ unknown }}!", {})
        self.assertEqual(result, "Hello !")

    def test_empty_body(self) -> None:
        self.assertEqual(_render_template("", {"key": "val"}), "")


class DefaultTextTest(TestCase):
    def test_personalized_contains_name_and_amount(self) -> None:
        text = _default_personalized_text("Bob", Decimal("75"))
        self.assertIn("Bob", text)
        self.assertIn("75", text)

    def test_gratitude_contains_name(self) -> None:
        text = _default_gratitude_text("Carol")
        self.assertIn("Carol", text)


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------

class DonationIngestSerializerTest(TestCase):
    def setUp(self) -> None:
        self.charity = make_charity()

    def _serializer(self, data: dict):
        from charity.api.serializers import DonationIngestSerializer
        return DonationIngestSerializer(data=data)

    def test_valid_payload(self) -> None:
        s = self._serializer({
            "charity_id": self.charity.id,
            "donor_email": "x@example.com",
            "donor_name": "X User",
            "amount": "100.00",
        })
        self.assertTrue(s.is_valid(), s.errors)

    def test_invalid_charity_id(self) -> None:
        s = self._serializer({
            "charity_id": 9999,
            "donor_email": "x@example.com",
            "donor_name": "X",
            "amount": "10.00",
        })
        self.assertFalse(s.is_valid())
        self.assertIn("charity_id", s.errors)

    def test_negative_amount_rejected(self) -> None:
        s = self._serializer({
            "charity_id": self.charity.id,
            "donor_email": "x@example.com",
            "donor_name": "X",
            "amount": "-5.00",
        })
        self.assertFalse(s.is_valid())
        self.assertIn("amount", s.errors)

    def test_defaults_donated_at(self) -> None:
        s = self._serializer({
            "charity_id": self.charity.id,
            "donor_email": "x@example.com",
            "donor_name": "X",
            "amount": "20.00",
        })
        self.assertTrue(s.is_valid())
        self.assertIn("donated_at", s.validated_data)


# ---------------------------------------------------------------------------
# API view tests
# ---------------------------------------------------------------------------

class DonationIngestAPIViewTest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(username="apiuser", password="pass")
        self.client.force_authenticate(user=self.user)
        self.charity = make_charity("API Charity")
        make_campaign(self.charity)

    def _post(self, payload: dict):
        return self.client.post(
            reverse("donation-ingest"),
            data=payload,
            format="json",
        )

    @patch("charity.services.video_dispatch.send_video_email", return_value={"id": "msg-123"})
    @patch("charity.services.video_dispatch.upload_video_to_stream", return_value=None)
    @patch("charity.services.video_dispatch.stitch_voice_and_overlay", return_value="/tmp/out.mp4")
    @patch("charity.services.video_dispatch.generate_voiceover", return_value="/tmp/vo.mp3")
    def test_ingest_creates_donation(
        self,
        _mock_vo: MagicMock,
        _mock_stitch: MagicMock,
        _mock_stream: MagicMock,
        _mock_email: MagicMock,
    ) -> None:
        with patch("django.conf.settings.CLOUDFLARE_STREAM_ENABLED", False):
            resp = self._post({
                "charity_id": self.charity.id,
                "donor_email": "jane@example.com",
                "donor_name": "Jane",
                "amount": "50.00",
                "campaign_type": "THANK_YOU",
            })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("donation_id", resp.data)
        self.assertTrue(Donation.objects.filter(charity=self.charity).exists())

    def test_missing_amount_returns_400(self) -> None:
        resp = self._post({
            "charity_id": self.charity.id,
            "donor_email": "jane@example.com",
            "donor_name": "Jane",
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_returns_401(self) -> None:
        self.client.force_authenticate(user=None)
        resp = self._post({
            "charity_id": self.charity.id,
            "donor_email": "jane@example.com",
            "donor_name": "Jane",
            "amount": "50.00",
        })
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class BulkDonationIngestAPIViewTest(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(username="bulkuser", password="pass")
        self.client.force_authenticate(user=self.user)
        self.charity = make_charity("Bulk Charity")
        make_campaign(self.charity)

    @patch("charity.services.video_dispatch.send_video_email", return_value={"id": "msg-bulk"})
    @patch("charity.services.video_dispatch.upload_video_to_stream", return_value=None)
    @patch("charity.services.video_dispatch.stitch_voice_and_overlay", return_value="/tmp/out.mp4")
    @patch("charity.services.video_dispatch.generate_voiceover", return_value="/tmp/vo.mp3")
    def test_bulk_ingest(
        self,
        _mock_vo: MagicMock,
        _mock_stitch: MagicMock,
        _mock_stream: MagicMock,
        _mock_email: MagicMock,
    ) -> None:
        with patch("django.conf.settings.CLOUDFLARE_STREAM_ENABLED", False):
            resp = self.client.post(
                reverse("donation-bulk-ingest"),
                data={
                    "donations": [
                        {
                            "charity_id": self.charity.id,
                            "donor_email": f"donor{i}@example.com",
                            "donor_name": f"Donor {i}",
                            "amount": "25.00",
                            "campaign_type": "THANK_YOU",
                        }
                        for i in range(3)
                    ]
                },
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(resp.data["results"]), 3)


# ---------------------------------------------------------------------------
# Dispatch service integration (all I/O mocked)
# ---------------------------------------------------------------------------

class DispatchDonationVideoTest(TestCase):
    def setUp(self) -> None:
        self.charity = make_charity("Dispatch Charity")
        self.campaign = make_campaign(self.charity, video_mode=Campaign.VideoMode.PERSONALIZED)

    @patch("charity.services.video_dispatch.send_video_email", return_value={"id": "msg-1"})
    @patch("charity.services.video_dispatch.upload_video_to_stream", return_value=None)
    @patch("charity.services.video_dispatch.stitch_voice_and_overlay", return_value="/tmp/video.mp4")
    @patch("charity.services.video_dispatch.generate_voiceover", return_value="/tmp/vo.mp3")
    def test_dispatch_creates_donor_donation_log(
        self,
        _mock_vo: MagicMock,
        _mock_stitch: MagicMock,
        _mock_stream: MagicMock,
        _mock_email: MagicMock,
    ) -> None:
        from charity.services.video_dispatch import dispatch_donation_video

        with patch("django.conf.settings.CLOUDFLARE_STREAM_ENABLED", False):
            result = dispatch_donation_video(
                charity=self.charity,
                donor_email="alice@example.com",
                donor_name="Alice",
                amount=Decimal("100"),
                donated_at=timezone.now(),
                source="TEST",
                campaign_type=Campaign.CampaignType.THANK_YOU,
            )

        self.assertEqual(result.donor_email, "alice@example.com")
        self.assertEqual(result.send_kind, VideoSendLog.SendKind.PERSONALIZED)
        self.assertTrue(Donor.objects.filter(email="alice@example.com").exists())
        log = VideoSendLog.objects.get(id=result.send_log_id)
        self.assertEqual(log.status, VideoSendLog.Status.SENT)

