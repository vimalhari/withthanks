import base64
import hashlib
import hmac
import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from charity.models import Campaign, Charity, DonationBatch, DonationJob, EmailTracking
from charity.utils.tracking_security import build_tracking_token


class MultiTenantIsolationTests(TestCase):
    def setUp(self):
        # Create two users/charities
        self.user_a = User.objects.create_user(username="charity_a", password="password")
        self.charity_a = Charity.objects.create(client_name="Charity A", contact_email="a@test.com")

        self.user_b = User.objects.create_user(username="charity_b", password="password")
        self.charity_b = Charity.objects.create(client_name="Charity B", contact_email="b@test.com")

        self.client = Client()

        # Create data for Charity A
        self.batch_a = DonationBatch.objects.create(charity=self.charity_a, batch_number=1)
        self.job_a = DonationJob.objects.create(
            donation_batch=self.batch_a,
            donor_name="Donor A",
            email="a@test.com",
            donation_amount=Decimal("10"),
        )

        # Create data for Charity B
        self.batch_b = DonationBatch.objects.create(charity=self.charity_b, batch_number=2)
        self.job_b = DonationJob.objects.create(
            donation_batch=self.batch_b,
            donor_name="Donor B",
            email="b@test.com",
            donation_amount=Decimal("20"),
        )

    def test_dashboard_isolation(self):
        """Charity A should only see Charity A (Self), not Charity B"""
        self.client.login(username="charity_a", password="password")
        # Dashboards are usually restricted to members
        from charity.models import CharityMember

        CharityMember.objects.create(charity=self.charity_a, user=self.user_a, role="Admin")

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        # Context badge renders charity name in uppercase
        self.assertContains(response, "CHARITY A")
        self.assertNotContains(response, "CHARITY B")


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class VideoProcessingIsolationTests(TestCase):
    def setUp(self):
        # Create fake base video files so file-open calls don't fail in CI
        media_test_dir = Path(settings.MEDIA_ROOT) / "test"
        media_test_dir.mkdir(parents=True, exist_ok=True)
        (media_test_dir / "fake_video_a.mp4").write_bytes(b"fake")
        (media_test_dir / "fake_video_b.mp4").write_bytes(b"fake")

        self.charity_a = Charity.objects.create(
            client_name="Charity A", contact_email="a@charity.org"
        )
        self.charity_b = Charity.objects.create(
            client_name="Charity B", contact_email="b@charity.org"
        )

        # Campaigns with scripts/settings replacing templates
        self.campaign_a = Campaign.objects.create(
            name="Campaign A",
            client=self.charity_a,
            campaign_start=date.today(),
            campaign_end=date.today(),
            video_mode=Campaign.VideoMode.PERSONALIZED,
        )
        self.charity_a.default_voiceover_script = "Hello A {{donor_name}}"
        # Provide a fake base video path (os.path.exists is mocked True in tests)
        self.charity_a.save()
        Charity.objects.filter(pk=self.charity_a.pk).update(
            default_template_video="test/fake_video_a.mp4"
        )

        self.campaign_b = Campaign.objects.create(
            name="Campaign B",
            client=self.charity_b,
            campaign_start=date.today(),
            campaign_end=date.today(),
            video_mode=Campaign.VideoMode.PERSONALIZED,
        )
        self.charity_b.default_voiceover_script = "Hello B {{donor_name}}"
        self.charity_b.save()
        Charity.objects.filter(pk=self.charity_b.pk).update(
            default_template_video="test/fake_video_b.mp4"
        )

        # Jobs for A — must link campaign so is_personalized is reachable
        self.batch_a = DonationBatch.objects.create(
            charity=self.charity_a, campaign=self.campaign_a, batch_number=1
        )
        self.job_a = DonationJob.objects.create(
            donation_batch=self.batch_a,
            donor_name="Donor A",
            email="donor@a.com",
            donation_amount=Decimal("10"),
            charity=self.charity_a,
            campaign=self.campaign_a,
        )

        # Jobs for B — must link campaign so is_personalized is reachable
        self.batch_b = DonationBatch.objects.create(
            charity=self.charity_b, campaign=self.campaign_b, batch_number=1
        )
        self.job_b = DonationJob.objects.create(
            donation_batch=self.batch_b,
            donor_name="Donor B",
            email="donor@b.com",
            donation_amount=Decimal("20"),
            charity=self.charity_b,
            campaign=self.campaign_b,
        )

    @patch(
        "charity.utils.video_utils.upload_output_to_r2", return_value="https://r2.example.com/v.mp4"
    )
    @patch("charity.services.video_build_service.generate_voiceover")
    @patch("charity.services.video_build_service.concat_intro_to_base")
    @patch("charity.services.video_build_service.generate_intro_clip")
    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.stream_safe_upload", return_value=None)
    @patch("os.path.exists")
    def test_processing_isolation(
        self,
        mock_exists,
        mock_stream,
        mock_send,
        mock_generate_intro,
        mock_concat,
        mock_tts,
        mock_upload,
    ):
        """Verify that jobs for different charities use their respective templates/branding"""
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        mock_exists.return_value = True
        mock_tts.return_value = "/tmp/tts.mp3"
        mock_generate_intro.return_value = "/tmp/intro.mp4"
        mock_concat.return_value = "/tmp/final.mp4"
        mock_send.return_value = {"id": "test-resend-id"}

        # Process Job A through all 3 stages
        ctx = validate_and_prep_job.run(self.job_a.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        # Verify Job A used Script A and Sender A
        self.assertIn("Hello A Donor A", mock_tts.call_args[1]["text"])
        self.assertEqual(mock_send.call_args[1]["from_email"], "a@charity.org")
        self.assertIsNone(mock_send.call_args[1]["file_path"])

        # Reset mocks
        mock_tts.reset_mock()
        mock_send.reset_mock()

        # Process Job B through all 3 stages
        ctx = validate_and_prep_job.run(self.job_b.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        # Verify Job B used Script B and Sender B
        self.assertIn("Hello B Donor B", mock_tts.call_args[1]["text"])
        self.assertEqual(mock_send.call_args[1]["from_email"], "b@charity.org")
        self.assertIsNone(mock_send.call_args[1]["file_path"])


class VideoDispatchServiceTests(TestCase):
    def setUp(self):
        self.charity = Charity.objects.create(
            client_name="Dispatch Charity",
            contact_email="ops@charity.org",
            organization_name="Dispatch Org",
        )
        self.campaign = Campaign.objects.create(
            name="Dispatch Campaign",
            client=self.charity,
            campaign_code="DSP-001",
            campaign_start=date.today(),
            campaign_end=date.today(),
            status="active",
            campaign_type=Campaign.CampaignType.THANK_YOU,
            input_source=Campaign.InputSource.API,
            video_mode=Campaign.VideoMode.PERSONALIZED,
            from_email="campaign@charity.org",
        )

    @patch("charity.services.video_dispatch_service.os.remove")
    @patch("charity.services.video_dispatch_service.send_video_email")
    @patch("charity.services.video_dispatch_service.stream_safe_upload")
    @patch("charity.services.video_dispatch_service._build_personalized_video")
    def test_dispatch_donation_video_prefers_stream_url_in_email(
        self,
        mock_build_video,
        mock_stream_upload,
        mock_send_email,
        mock_remove,
    ):
        from charity.services.video_dispatch_service import dispatch_donation_video

        mock_build_video.return_value = (
            "/tmp/final.mp4",
            "https://r2.example.com/videos/final.mp4",
        )
        mock_stream_upload.return_value = SimpleNamespace(
            video_id="stream-123",
            playback_url="https://stream.example.com/videos/stream-123",
            thumbnail_url="https://stream.example.com/videos/stream-123/thumb.jpg",
        )
        mock_send_email.return_value = {"id": "resend-123"}

        result = dispatch_donation_video(
            charity=self.charity,
            donor_email="donor@example.com",
            donor_name="Donor Name",
            amount=Decimal("25.00"),
        )

        self.assertEqual(result.stream_playback_url, "https://stream.example.com/videos/stream-123")
        self.assertEqual(result.video_path, "https://r2.example.com/videos/final.mp4")
        self.assertTrue(mock_remove.called)
        mock_send_email.assert_called_once()
        self.assertEqual(
            mock_send_email.call_args.kwargs["video_url"],
            "https://stream.example.com/videos/stream-123",
        )
        self.assertIsNone(mock_send_email.call_args.kwargs["file_path"])
        self.assertEqual(mock_send_email.call_args.kwargs["from_email"], "campaign@charity.org")
        self.assertEqual(mock_send_email.call_args.kwargs["organization_name"], "Dispatch Org")
        self.assertEqual(mock_send_email.call_args.kwargs["subject"], "Dispatch Campaign")

    @patch("charity.services.video_dispatch_service.os.remove")
    @patch("charity.services.video_dispatch_service.send_video_email")
    @patch("charity.services.video_dispatch_service.stream_safe_upload", return_value=None)
    @patch("charity.services.video_dispatch_service._build_template_video_path")
    def test_dispatch_donation_video_falls_back_to_template_public_url(
        self,
        mock_build_template,
        mock_stream_upload,
        mock_send_email,
        mock_remove,
    ):
        from charity.services.video_dispatch_service import dispatch_donation_video

        self.campaign.video_mode = Campaign.VideoMode.TEMPLATE
        self.campaign.save(update_fields=["video_mode"])

        mock_build_template.return_value = (
            "/tmp/template.mp4",
            "https://cdn.example.com/templates/template.mp4",
        )
        mock_send_email.return_value = {"id": "resend-456"}

        result = dispatch_donation_video(
            charity=self.charity,
            donor_email="donor@example.com",
            donor_name="Donor Name",
            amount=Decimal("10.00"),
        )

        self.assertEqual(result.video_path, "https://cdn.example.com/templates/template.mp4")
        mock_send_email.assert_called_once()
        self.assertEqual(
            mock_send_email.call_args.kwargs["video_url"],
            "https://cdn.example.com/templates/template.mp4",
        )
        self.assertIsNone(mock_send_email.call_args.kwargs["file_path"])


@override_settings(RESEND_API_KEY="test-resend-key", DEFAULT_FROM_EMAIL="noreply@example.com")
class ResendUtilsTests(TestCase):
    @patch("charity.utils.resend_utils.resend.Emails.send", return_value={"id": "resend-789"})
    def test_send_video_email_skips_local_video_attachment(self, mock_resend_send):
        from charity.utils.resend_utils import send_video_email

        temp_dir = Path(tempfile.mkdtemp())
        local_video = temp_dir / "local-video.mp4"
        local_video.write_bytes(b"fake-video")

        send_video_email(
            to_email="donor@example.com",
            file_path=str(local_video),
            job_id="job-123",
            donor_name="Donor",
            donation_amount="20",
            organization_name="WithThanks",
            from_email="sender@example.com",
            video_url="https://stream.example.com/videos/stream-123",
        )

        params = mock_resend_send.call_args.args[0]
        self.assertNotIn("attachments", params)
        self.assertIn("https://stream.example.com/videos/stream-123", params["html"])

    @patch("charity.utils.resend_utils.resend.Emails.send", return_value={"id": "resend-789"})
    def test_send_video_email_uses_signed_tracking_links(self, mock_resend_send):
        from charity.utils.resend_utils import send_video_email

        send_video_email(
            to_email="donor@example.com",
            file_path=None,
            job_id="job-123",
            donor_name="Donor",
            donation_amount="20",
            organization_name="WithThanks",
            from_email="sender@example.com",
            video_url="https://stream.example.com/videos/stream-123",
            tracking_token="signed-tracking-token",
        )

        params = mock_resend_send.call_args.args[0]
        self.assertIn(
            'src="http://127.0.0.1:8000/charity/track/open/?t=signed-tracking-token"',
            params["html"],
        )
        self.assertIn(
            'href="http://127.0.0.1:8000/charity/track/click/?t=signed-tracking-token"',
            params["html"],
        )
        self.assertIn(
            'href="http://127.0.0.1:8000/charity/track/unsubscribe/?t=signed-tracking-token"',
            params["html"],
        )


class TrackingSecurityTests(TestCase):
    def setUp(self):
        today = date.today()
        self.charity = Charity.objects.create(
            client_name="Tracking Charity",
            contact_email="ops@charity.org",
            organization_name="Tracking Org",
        )
        self.campaign = Campaign.objects.create(
            name="Tracking Campaign",
            client=self.charity,
            campaign_code="TRK-001",
            campaign_start=today,
            campaign_end=today,
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
        )
        self.batch = DonationBatch.objects.create(charity=self.charity, campaign=self.campaign)
        self.job = DonationJob.objects.create(
            charity=self.charity,
            campaign=self.campaign,
            donation_batch=self.batch,
            donor_name="Tracked Donor",
            email="tracked@example.com",
            donation_amount=Decimal("25.00"),
            status="success",
            video_path="https://cdn.example.com/video.mp4",
        )
        self.tracking = EmailTracking.objects.create(
            campaign=self.campaign,
            batch=self.batch,
            job=self.job,
            user_id=self.job.id,
            campaign_type=self.campaign.campaign_type,
        )

    def test_track_open_accepts_signed_tracking_token(self):
        token = build_tracking_token(tracking_id=self.tracking.id)

        response = self.client.get(reverse("track_open"), {"t": token})

        self.assertEqual(response.status_code, 200)
        self.tracking.refresh_from_db()
        self.job.refresh_from_db()
        self.assertTrue(self.tracking.opened)
        self.assertEqual(self.job.real_views, 1)

    def test_track_click_accepts_signed_tracking_token(self):
        token = build_tracking_token(tracking_id=self.tracking.id)

        response = self.client.get(reverse("track_click"), {"t": token})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"http://127.0.0.1:8000{reverse('video_landing', args=[self.job.id])}",
        )
        self.tracking.refresh_from_db()
        self.job.refresh_from_db()
        self.assertTrue(self.tracking.clicked)
        self.assertEqual(self.job.real_clicks, 1)


@override_settings(WEBHOOK_SIGNATURE_MAX_AGE_SECONDS=300)
class WebhookSecurityTests(TestCase):
    def _build_resend_signature(self, body: bytes, timestamp: int, secret: str) -> str:
        key = base64.b64decode(secret[6:])
        signed_content = f"msg-1.{timestamp}.{body.decode('utf-8')}"
        digest = hmac.new(key, signed_content.encode("utf-8"), hashlib.sha256).digest()
        return f"v1,{base64.b64encode(digest).decode()}"

    def _build_cloudflare_signature(self, body: bytes, timestamp: int, secret: str) -> str:
        digest = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}{body.decode('utf-8')}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"time={timestamp};sig1={digest}"

    @override_settings(RESEND_WEBHOOK_SECRET="whsec_c2VjcmV0LWtleQ==")
    def test_resend_webhook_rejects_stale_signature(self):
        timestamp = 1
        payload = {"type": "email.sent", "data": {"id": "msg-123"}}
        body = json.dumps(payload).encode("utf-8")
        signature = self._build_resend_signature(body, timestamp, settings.RESEND_WEBHOOK_SECRET)

        response = self.client.post(
            reverse("resend_webhook"),
            data=body,
            content_type="application/json",
            **{
                "HTTP_SVIX_ID": "msg-1",
                "HTTP_SVIX_TIMESTAMP": str(timestamp),
                "HTTP_SVIX_SIGNATURE": signature,
            },
        )

        self.assertEqual(response.status_code, 401)

    @override_settings(CLOUDFLARE_WEBHOOK_SECRET="cloudflare-secret")
    def test_cloudflare_webhook_rejects_stale_signature(self):
        timestamp = 1
        payload = {"action": "video.play", "video_id": "vid-1", "meta": {}}
        body = json.dumps(payload).encode("utf-8")
        signature = self._build_cloudflare_signature(
            body,
            timestamp,
            settings.CLOUDFLARE_WEBHOOK_SECRET,
        )

        response = self.client.post(
            reverse("cloudflare_webhook"),
            data=body,
            content_type="application/json",
            **{"HTTP_WEBHOOK_SIGNATURE": signature},
        )

        self.assertEqual(response.status_code, 401)
