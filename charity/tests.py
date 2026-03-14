import base64
import hashlib
import hmac
import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from charity.admin import UnsubscribedUserAdmin
from charity.analytics_models import EmailEvent
from charity.models import (
    Campaign,
    Charity,
    CharityMember,
    DonationBatch,
    DonationJob,
    EmailTracking,
    UnsubscribedUser,
)
from charity.services.video_pipeline_service import StreamDelivery
from charity.utils.cloudflare_stream import extract_stream_video_id
from charity.utils.tracking_security import build_tracking_token


def build_stream_delivery(video_id: str = "stream-123") -> StreamDelivery:
    return StreamDelivery(
        video_id=video_id,
        playback_url=f"https://watch.cloudflarestream.com/{video_id}",
        thumbnail_url=f"https://videodelivery.net/{video_id}/thumbnails/thumbnail.jpg?time=2s&height=320",
    )


def build_test_image_upload(name: str = "logo.gif") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        (
            b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
            b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
            b"\x00\x02\x02D\x01\x00;"
        ),
        content_type="image/gif",
    )


class MultiTenantIsolationTests(TestCase):
    def setUp(self):
        # Create two users/charities
        self.user_a = User.objects.create_user(username="charity_a", password="password")
        self.charity_a = Charity.objects.create(
            charity_name="Charity A", contact_email="a@test.com"
        )

        self.user_b = User.objects.create_user(username="charity_b", password="password")
        self.charity_b = Charity.objects.create(
            charity_name="Charity B", contact_email="b@test.com"
        )

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
        CharityMember.objects.create(charity=self.charity_a, user=self.user_a, role="Admin")

        response = self.client.get(reverse("dashboard"), follow=True)
        self.assertRedirects(response, reverse("analytics_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Analytics & Reports")
        # Context badge renders charity name in uppercase
        self.assertContains(response, "CHARITY A")
        self.assertNotContains(response, "CHARITY B")


class UnsubscribeAdminActionTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="password123",
            is_staff=True,
        )
        self.charity = Charity.objects.create(
            charity_name="Action Charity",
            contact_email="ops@action.org",
        )
        self.selected_unsub = UnsubscribedUser.objects.create(
            charity=self.charity,
            email="selected@example.com",
            reason="Clicked unsubscribe link",
        )
        self.other_unsub = UnsubscribedUser.objects.create(
            charity=self.charity,
            email="other@example.com",
            reason="Clicked unsubscribe link",
        )
        self.client = Client()
        self.factory = RequestFactory()

    def test_admin_action_resubscribes_only_selected_unsubscribes(self):
        self.client.login(username="admin", password="password123")

        response = self.client.post(
            reverse("admin:charity_unsubscribeduser_changelist"),
            {
                "action": "resubscribe_selected_donors",
                "_selected_action": [str(self.selected_unsub.pk)],
                "index": 0,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(UnsubscribedUser.objects.filter(pk=self.selected_unsub.pk).exists())
        self.assertTrue(UnsubscribedUser.objects.filter(pk=self.other_unsub.pk).exists())

    def test_admin_action_requires_superuser(self):
        request = self.factory.post(reverse("admin:charity_unsubscribeduser_changelist"))
        request.user = self.staff_user
        model_admin = UnsubscribedUserAdmin(UnsubscribedUser, admin.site)

        with self.assertRaises(PermissionDenied):
            model_admin.actions[0](
                model_admin,
                request,
                UnsubscribedUser.objects.filter(pk=self.selected_unsub.pk),
            )


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
            charity_name="Charity A", contact_email="a@charity.org"
        )
        self.charity_b = Charity.objects.create(
            charity_name="Charity B", contact_email="b@charity.org"
        )

        # Campaigns with scripts/settings replacing templates
        self.campaign_a = Campaign.objects.create(
            name="Campaign A",
            charity=self.charity_a,
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.THANK_YOU_PERSONALIZED,
            from_email="sender-a@charity.org",
            voiceover_script="Hello A {{donor_name}}",
        )
        # Provide a fake base video path (os.path.exists is mocked True in tests)
        Campaign.objects.filter(pk=self.campaign_a.pk).update(base_video="test/fake_video_a.mp4")

        self.campaign_b = Campaign.objects.create(
            name="Campaign B",
            charity=self.charity_b,
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.THANK_YOU_PERSONALIZED,
            from_email="sender-b@charity.org",
            voiceover_script="Hello B {{donor_name}}",
        )
        Campaign.objects.filter(pk=self.campaign_b.pk).update(base_video="test/fake_video_b.mp4")

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
    @patch("charity.tasks.stream_safe_upload")
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
        mock_stream.return_value = build_stream_delivery("stream-a")
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
        self.assertEqual(mock_send.call_args[1]["from_email"], "sender-a@charity.org")
        self.assertIsNone(mock_send.call_args[1]["file_path"])
        self.assertEqual(
            mock_send.call_args[1]["video_url"],
            "https://watch.cloudflarestream.com/stream-a",
        )
        self.job_a.refresh_from_db()
        self.assertEqual(self.job_a.video_path, "https://watch.cloudflarestream.com/stream-a")

        # Reset mocks
        mock_tts.reset_mock()
        mock_send.reset_mock()
        mock_stream.return_value = build_stream_delivery("stream-b")

        # Process Job B through all 3 stages
        ctx = validate_and_prep_job.run(self.job_b.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        # Verify Job B used Script B and Sender B
        self.assertIn("Hello B Donor B", mock_tts.call_args[1]["text"])
        self.assertEqual(mock_send.call_args[1]["from_email"], "sender-b@charity.org")
        self.assertIsNone(mock_send.call_args[1]["file_path"])
        self.assertEqual(
            mock_send.call_args[1]["video_url"],
            "https://watch.cloudflarestream.com/stream-b",
        )
        self.job_b.refresh_from_db()
        self.assertEqual(self.job_b.video_path, "https://watch.cloudflarestream.com/stream-b")

    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.get_or_upload_campaign_stream", return_value=StreamDelivery())
    def test_vdm_fails_when_stream_unavailable(
        self,
        mock_stream_delivery,
        mock_send,
    ):
        """VDM should fail instead of sending a local-storage fallback URL."""
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        vdm_campaign = Campaign.objects.create(
            name="VDM Campaign",
            charity=self.charity_a,
            campaign_code="VDM-001",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")
        vdm_campaign.refresh_from_db()

        vdm_batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=2,
        )
        vdm_job = DonationJob.objects.create(
            donation_batch=vdm_batch,
            donor_name="VDM Donor",
            email="vdm@example.com",
            donation_amount=Decimal("15"),
            charity=self.charity_a,
            campaign=vdm_campaign,
        )

        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        result = dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        self.assertEqual(result["status"], "failed")
        mock_send.assert_not_called()
        vdm_job.refresh_from_db()
        self.assertEqual(vdm_job.status, "failed")
        self.assertIn("Cloudflare Stream upload required", vdm_job.error_message)

    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.get_or_upload_campaign_stream")
    def test_vdm_uses_campaign_configured_email_body(
        self,
        mock_stream,
        mock_send,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        vdm_campaign = Campaign.objects.create(
            name="Custom Copy Campaign",
            charity=self.charity_a,
            campaign_code="VDM-005",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
            email_body=(
                "Welcome to {{ campaign_name }} from {{ charity_name }}.\n\n"
                "We made this update for {{ donor_name }}."
            ),
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")
        vdm_campaign.refresh_from_db()

        vdm_batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=6,
        )
        vdm_job = DonationJob.objects.create(
            donation_batch=vdm_batch,
            donor_name="Jane",
            email="custom@example.com",
            donation_amount=Decimal("15"),
            charity=self.charity_a,
            campaign=vdm_campaign,
        )

        mock_stream.return_value = build_stream_delivery("stream-copy")
        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn("Welcome to Custom Copy Campaign from", html)
        self.assertIn("We made this update for Jane.", html)
        self.assertNotIn("We are excited to share some amazing updates with you!", html)

    @override_settings(DEFAULT_FROM_EMAIL="noreply@example.com")
    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.get_or_upload_campaign_stream")
    def test_vdm_falls_back_to_default_from_email_when_campaign_sender_missing(
        self,
        mock_stream,
        mock_send,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        vdm_campaign = Campaign.objects.create(
            name="Default Sender Campaign",
            charity=self.charity_a,
            campaign_code="VDM-006",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")
        vdm_campaign.refresh_from_db()

        vdm_batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=7,
        )
        vdm_job = DonationJob.objects.create(
            donation_batch=vdm_batch,
            donor_name="Fallback Sender",
            email="fallback@example.com",
            donation_amount=Decimal("15"),
            charity=self.charity_a,
            campaign=vdm_campaign,
        )

        mock_stream.return_value = build_stream_delivery("stream-sender")
        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        self.assertEqual(mock_send.call_args[1]["from_email"], "noreply@example.com")

    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.get_or_upload_campaign_stream")
    def test_vdm_uses_stream_thumbnail_when_campaign_thumbnail_is_local_only(
        self,
        mock_stream,
        mock_send,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        thumbnail = SimpleUploadedFile(
            "vdm-thumb.gif",
            (
                b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
                b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
                b"\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )
        vdm_campaign = Campaign.objects.create(
            name="Thumbnail Campaign",
            charity=self.charity_a,
            campaign_code="VDM-006",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
            email_thumbnail=thumbnail,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")
        vdm_campaign.refresh_from_db()

        vdm_batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=7,
        )
        vdm_job = DonationJob.objects.create(
            donation_batch=vdm_batch,
            donor_name="Thumbnail Donor",
            email="thumb@example.com",
            donation_amount=Decimal("15"),
            charity=self.charity_a,
            campaign=vdm_campaign,
        )

        mock_stream.return_value = build_stream_delivery("stream-thumb")
        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn('src="https://videodelivery.net/stream-thumb/thumbnails/thumbnail.jpg', html)
        self.assertNotIn('src="http://127.0.0.1:8000/media/', html)
        self.assertIn('href="http://127.0.0.1:8000/charity/track/click/?t=', html)

    @patch(
        "charity.utils.video_utils.upload_output_to_r2", return_value="https://r2.example.com/v.mp4"
    )
    @patch("charity.services.video_build_service.generate_voiceover")
    @patch("charity.services.video_build_service.concat_intro_to_base")
    @patch("charity.services.video_build_service.generate_intro_clip")
    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.stream_safe_upload")
    @patch("charity.tasks.resolve_storage_video_url")
    @patch("os.path.exists")
    def test_withthanks_email_includes_public_charity_logo_without_replacing_banner(
        self,
        mock_exists,
        mock_resolve_storage_url,
        mock_stream,
        mock_send,
        mock_generate_intro,
        mock_concat,
        mock_tts,
        _mock_upload,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        mock_exists.return_value = True
        mock_stream.return_value = build_stream_delivery("stream-logo")
        mock_tts.return_value = "/tmp/tts.mp3"
        mock_generate_intro.return_value = "/tmp/intro.mp4"
        mock_concat.return_value = "/tmp/final.mp4"
        mock_send.return_value = {"id": "test-resend-id"}

        self.charity_a.logo = build_test_image_upload("charity-logo.gif")
        self.charity_a.save(update_fields=["logo"])
        self.campaign_a.email_thumbnail = build_test_image_upload("campaign-banner.gif")
        self.campaign_a.save(update_fields=["email_thumbnail"])
        self.charity_a.refresh_from_db()
        self.campaign_a.refresh_from_db()

        resolved_urls = {
            self.charity_a.logo.name: f"https://assets.example.com/{self.charity_a.logo.name}",
            self.campaign_a.email_thumbnail.name: (
                f"https://assets.example.com/{self.campaign_a.email_thumbnail.name}"
            ),
        }
        mock_resolve_storage_url.side_effect = lambda *, storage_path, server_url: (
            resolved_urls.get(storage_path, "")
        )

        ctx = validate_and_prep_job.run(self.job_a.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn(f'src="https://assets.example.com/{self.charity_a.logo.name}"', html)
        self.assertIn(
            f'src="https://assets.example.com/{self.campaign_a.email_thumbnail.name}"',
            html,
        )

    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.get_or_upload_campaign_stream")
    def test_dispatch_skips_unsubscribed_vdm_before_delivery_side_effects(
        self,
        mock_stream,
        mock_send,
    ):
        from charity.tasks import dispatch_email_for_job, validate_and_prep_job

        vdm_campaign = Campaign.objects.create(
            name="Suppressed VDM Campaign",
            charity=self.charity_a,
            campaign_code="VDM-009",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        vdm_batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=10,
        )
        vdm_job = DonationJob.objects.create(
            donation_batch=vdm_batch,
            donor_name="Suppressed Donor",
            email="suppressed@example.com",
            donation_amount=Decimal("15"),
            charity=self.charity_a,
            campaign=vdm_campaign,
        )
        UnsubscribedUser.objects.create(
            charity=self.charity_a,
            email=vdm_job.email,
            reason="Requested no more VDM",
        )

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        result = dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        self.assertEqual(result["status"], "skipped")
        mock_stream.assert_not_called()
        mock_send.assert_not_called()

        vdm_job.refresh_from_db()
        self.assertEqual(vdm_job.status, "skipped")
        self.assertEqual(vdm_job.campaign_type, "VDM")
        self.assertIsNotNone(vdm_job.completed_at)
        self.assertIn("Suppressed VDM email", vdm_job.error_message)
        self.assertFalse(EmailTracking.objects.filter(job=vdm_job).exists())
        self.assertFalse(EmailEvent.objects.filter(job=vdm_job, event_type="SENT").exists())

    @patch(
        "charity.utils.video_utils.upload_output_to_r2", return_value="https://r2.example.com/v.mp4"
    )
    @patch("charity.services.video_build_service.generate_voiceover")
    @patch("charity.services.video_build_service.concat_intro_to_base")
    @patch("charity.services.video_build_service.generate_intro_clip")
    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.stream_safe_upload")
    @patch("os.path.exists")
    def test_withthanks_does_not_apply_vdm_unsubscribe_suppression(
        self,
        mock_exists,
        mock_stream,
        mock_send,
        mock_generate_intro,
        mock_concat,
        mock_tts,
        mock_upload,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        mock_exists.return_value = True
        mock_stream.return_value = build_stream_delivery("stream-no-suppress")
        mock_tts.return_value = "/tmp/tts.mp3"
        mock_generate_intro.return_value = "/tmp/intro.mp4"
        mock_concat.return_value = "/tmp/final.mp4"
        mock_send.return_value = {"id": "test-resend-id"}

        UnsubscribedUser.objects.create(
            charity=self.charity_a,
            email=self.job_a.email,
            reason="Legacy unsubscribe record",
        )

        ctx = validate_and_prep_job.run(self.job_a.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        result = dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        self.assertEqual(result["status"], "success")
        mock_send.assert_called_once()

        self.job_a.refresh_from_db()
        self.assertEqual(self.job_a.status, "success")
        self.assertTrue(EmailTracking.objects.filter(job=self.job_a, sent=True).exists())
        self.assertTrue(EmailEvent.objects.filter(job=self.job_a, event_type="SENT").exists())

    @override_settings(PUBLIC_MEDIA_BASE_URL="")
    @patch(
        "charity.services.video_pipeline_service._storage_uses_local_filesystem", return_value=False
    )
    @patch("django.core.files.storage.default_storage", new_callable=Mock)
    def test_resolve_storage_video_url_treats_r2_api_endpoint_as_non_public(
        self,
        mock_storage,
        _mock_local_storage,
    ):
        from charity.services.video_pipeline_service import resolve_storage_video_url

        storage_path = "charities/charity_2/campaign_overrides/thumb.jpg"
        mock_storage.exists.return_value = True
        mock_storage.url.return_value = (
            "https://example-account.r2.cloudflarestorage.com/withthanks/"
            "charities/charity_2/campaign_overrides/thumb.jpg"
        )

        resolved_url = resolve_storage_video_url(
            storage_path=storage_path,
            server_url="http://127.0.0.1:8000",
        )

        self.assertEqual(resolved_url, "")

    @override_settings(PUBLIC_MEDIA_BASE_URL="https://assets.example.com")
    @patch(
        "charity.services.video_pipeline_service._storage_uses_local_filesystem", return_value=False
    )
    @patch("django.core.files.storage.default_storage", new_callable=Mock)
    def test_resolve_storage_video_url_uses_public_media_base_url_for_r2_assets(
        self,
        mock_storage,
        _mock_local_storage,
    ):
        from charity.services.video_pipeline_service import resolve_storage_video_url

        storage_path = "charities/charity_2/campaign_overrides/thumb.jpg"
        mock_storage.exists.return_value = True
        mock_storage.url.return_value = (
            "https://example-account.r2.cloudflarestorage.com/withthanks/"
            "charities/charity_2/campaign_overrides/thumb.jpg"
        )

        resolved_url = resolve_storage_video_url(
            storage_path=storage_path,
            server_url="http://127.0.0.1:8000",
        )

        self.assertEqual(
            resolved_url,
            "https://assets.example.com/charities/charity_2/campaign_overrides/thumb.jpg",
        )

    @patch(
        "charity.services.video_pipeline_service._storage_uses_local_filesystem", return_value=False
    )
    @patch("django.core.files.storage.default_storage", new_callable=Mock)
    def test_resolve_storage_video_url_returns_empty_when_storage_object_is_missing(
        self,
        mock_storage,
        _mock_local_storage,
    ):
        from charity.services.video_pipeline_service import resolve_storage_video_url

        storage_path = "charities/charity_2/campaign_overrides/missing-thumb.jpg"
        mock_storage.exists.return_value = False

        resolved_url = resolve_storage_video_url(
            storage_path=storage_path,
            server_url="http://127.0.0.1:8000",
        )

        self.assertEqual(resolved_url, "")
        mock_storage.url.assert_not_called()

    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.get_or_upload_campaign_stream")
    def test_vdm_omits_dear_for_title_surname_greeting(
        self,
        mock_stream,
        mock_send,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        vdm_campaign = Campaign.objects.create(
            name="Formal Greeting Campaign",
            charity=self.charity_a,
            campaign_code="VDM-007",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")
        vdm_campaign.refresh_from_db()

        vdm_batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=8,
        )
        vdm_job = DonationJob.objects.create(
            donation_batch=vdm_batch,
            donor_name="Ms Smith",
            email="formal@example.com",
            donation_amount=Decimal("15"),
            charity=self.charity_a,
            campaign=vdm_campaign,
        )

        mock_stream.return_value = build_stream_delivery("stream-formal")
        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn("Ms Smith,", html)
        self.assertNotIn("Dear Ms Smith,", html)

    @patch(
        "charity.utils.video_utils.upload_output_to_r2", return_value="https://r2.example.com/v.mp4"
    )
    @patch("charity.services.video_build_service.generate_voiceover")
    @patch("charity.services.video_build_service.concat_intro_to_base")
    @patch("charity.services.video_build_service.generate_intro_clip")
    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.stream_safe_upload")
    @patch("os.path.exists")
    def test_withthanks_omits_dear_for_title_surname_greeting(
        self,
        mock_exists,
        mock_stream,
        mock_send,
        mock_generate_intro,
        mock_concat,
        mock_tts,
        mock_upload,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        mock_exists.return_value = True
        mock_stream.return_value = build_stream_delivery("stream-greeting")
        mock_tts.return_value = "/tmp/tts.mp3"
        mock_generate_intro.return_value = "/tmp/intro.mp4"
        mock_concat.return_value = "/tmp/final.mp4"
        mock_send.return_value = {"id": "test-resend-id"}

        self.job_a.donor_name = "Ms Smith"
        self.job_a.save(update_fields=["donor_name"])

        ctx = validate_and_prep_job.run(self.job_a.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn("Ms Smith,", html)
        self.assertNotIn("Dear Ms Smith,", html)

    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.get_or_upload_campaign_stream")
    def test_vdm_footer_uses_website_url_when_present(
        self,
        mock_stream,
        mock_send,
    ):
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        self.charity_a.website_url = "https://charitya.example.org"
        self.charity_a.save(update_fields=["website_url"])

        vdm_campaign = Campaign.objects.create(
            name="Website Footer Campaign",
            charity=self.charity_a,
            campaign_code="VDM-008",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")
        vdm_campaign.refresh_from_db()

        vdm_batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=9,
        )
        vdm_job = DonationJob.objects.create(
            donation_batch=vdm_batch,
            donor_name="Jane",
            email="website@example.com",
            donation_amount=Decimal("15"),
            charity=self.charity_a,
            campaign=vdm_campaign,
        )

        mock_stream.return_value = build_stream_delivery("stream-footer")
        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn("https://charitya.example.org", html)
        self.assertNotIn("a@charity.org", html)

    def test_batch_process_csv_fails_fast_for_vdm_campaign_without_video(self):
        from charity.tasks import batch_process_csv

        vdm_campaign = Campaign.objects.create(
            name="Broken VDM Campaign",
            charity=self.charity_a,
            campaign_code="VDM-002",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )

        csv_key = default_storage.save(
            "uploads/test/vdm-preflight.csv",
            ContentFile(b"donor_name,email,donation_amount\nDonor,vdm@example.com,15.00\n"),
        )
        batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=3,
            csv_filename=csv_key,
        )

        batch_process_csv.run(batch.id)  # type: ignore[attr-defined]

        batch.refresh_from_db()
        self.assertEqual(batch.status, DonationBatch.BatchStatus.FAILED)
        self.assertEqual(DonationJob.objects.filter(donation_batch=batch).count(), 0)

    @patch("charity.tasks.chord")
    def test_batch_process_csv_dispatches_vdm_jobs_when_campaign_is_configured(self, mock_chord):
        from charity.tasks import batch_process_csv

        chord_runner = Mock()
        mock_chord.return_value = chord_runner

        vdm_campaign = Campaign.objects.create(
            name="Working VDM Campaign",
            charity=self.charity_a,
            campaign_code="VDM-003",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")

        csv_key = default_storage.save(
            "uploads/test/vdm-dispatch.csv",
            ContentFile(b"donor_name,email,donation_amount\nDonor,dispatch@example.com,15.00\n"),
        )
        batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=4,
            csv_filename=csv_key,
        )

        batch_process_csv.run(batch.id)  # type: ignore[attr-defined]

        batch.refresh_from_db()
        self.assertEqual(batch.status, DonationBatch.BatchStatus.PROCESSING)
        jobs = DonationJob.objects.filter(donation_batch=batch)
        self.assertEqual(jobs.count(), 1)
        queued_job = jobs.get()
        self.assertEqual(queued_job.campaign, vdm_campaign)
        self.assertEqual(mock_chord.call_count, 1)
        chord_runner.assert_called_once()

    @patch("charity.tasks.chord")
    def test_batch_process_csv_uses_first_name_then_title_surname_for_vdm(self, mock_chord):
        from charity.tasks import batch_process_csv

        chord_runner = Mock()
        mock_chord.return_value = chord_runner

        vdm_campaign = Campaign.objects.create(
            name="Greeting VDM Campaign",
            charity=self.charity_a,
            campaign_code="VDM-004",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(vdm_video="test/fake_video_a.mp4")

        csv_key = default_storage.save(
            "uploads/test/vdm-greetings.csv",
            ContentFile(
                b"Donor Name,Title,First Name,Surname,Email Address\n"
                b"Dr Jane Doe,Dr,Jane,Doe,jane@example.com\n"
                b"Supporter Record,Ms,,Smith,smith@example.com\n"
            ),
        )
        batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=vdm_campaign,
            batch_number=5,
            csv_filename=csv_key,
        )

        batch_process_csv.run(batch.id)  # type: ignore[attr-defined]

        jobs = DonationJob.objects.filter(donation_batch=batch).order_by("email")
        self.assertEqual(jobs.count(), 2)
        self.assertEqual(jobs[0].email, "jane@example.com")
        self.assertEqual(jobs[0].donor_name, "Jane")
        self.assertEqual(jobs[1].email, "smith@example.com")
        self.assertEqual(jobs[1].donor_name, "Ms Smith")

    def test_validate_and_prep_job_ignores_gratitude_video_for_standard_withthanks(self):
        from charity.tasks import validate_and_prep_job

        gratitude_path = Path(settings.MEDIA_ROOT) / "test" / "fake_gratitude.mp4"
        gratitude_path.write_bytes(b"gratitude")

        campaign = Campaign.objects.create(
            name="WithThanks Campaign",
            charity=self.charity_a,
            campaign_code="WT-001",
            campaign_start=date.today(),
            campaign_end=date.today(),
            campaign_mode=Campaign.CampaignMode.THANK_YOU_PERSONALIZED,
        )
        Campaign.objects.filter(pk=campaign.pk).update(
            gratitude_video="test/fake_gratitude.mp4",
            base_video="test/fake_video_a.mp4",
        )
        campaign.refresh_from_db()

        batch = DonationBatch.objects.create(
            charity=self.charity_a,
            campaign=campaign,
            batch_number=5,
        )
        job = DonationJob.objects.create(
            donation_batch=batch,
            donor_name="Standard Donor",
            email="standard@example.com",
            donation_amount=Decimal("20"),
            charity=self.charity_a,
            campaign=campaign,
        )

        ctx = validate_and_prep_job.run(job.id)  # type: ignore[attr-defined]

        self.assertEqual(ctx["mode"], "WithThanks")
        self.assertEqual(ctx["base_video_path"], "test/fake_video_a.mp4")


class DonationIngestAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="apiuser", password="password")
        self.charity = Charity.objects.create(
            charity_name="API Charity",
            contact_email="api@charity.org",
        )
        CharityMember.objects.create(
            charity=self.charity,
            user=self.user,
            role="Admin",
            status="ACTIVE",
        )
        self.api_client = APIClient()
        token = RefreshToken.for_user(self.user)
        self.api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    def test_single_ingest_rejects_vdm_campaign_type(self):
        response = self.api_client.post(
            reverse("donation-ingest"),
            {
                "charity_id": self.charity.id,
                "donor_email": "donor@example.com",
                "donor_name": "API Donor",
                "amount": "12.50",
                "campaign_type": "VDM",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["campaign_type"],
            ["VDM ingestion is only supported via CSV batch upload."],
        )
        self.assertEqual(DonationBatch.objects.count(), 0)
        self.assertEqual(DonationJob.objects.count(), 0)

    def test_bulk_ingest_rejects_vdm_campaign_type(self):
        response = self.api_client.post(
            reverse("donation-bulk-ingest"),
            {
                "donations": [
                    {
                        "charity_id": self.charity.id,
                        "donor_email": "bulk@example.com",
                        "donor_name": "Bulk Donor",
                        "amount": "15.00",
                        "campaign_type": "VDM",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["donations"][0]["campaign_type"],
            ["VDM ingestion is only supported via CSV batch upload."],
        )
        self.assertEqual(DonationBatch.objects.count(), 0)
        self.assertEqual(DonationJob.objects.count(), 0)


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
            charity_name="WithThanks",
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
            charity_name="WithThanks",
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
            charity_name="Tracking Charity",
            contact_email="ops@charity.org",
        )
        self.campaign = Campaign.objects.create(
            name="Tracking Campaign",
            charity=self.charity,
            campaign_code="TRK-001",
            campaign_start=today,
            campaign_end=today,
            campaign_mode=Campaign.CampaignMode.VDM,
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
            campaign_type="VDM" if self.campaign.is_vdm else "THANK_YOU",
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
        self.assertEqual(response["Location"], "https://cdn.example.com/video.mp4")
        self.tracking.refresh_from_db()
        self.job.refresh_from_db()
        self.assertTrue(self.tracking.clicked)
        self.assertEqual(self.job.real_clicks, 1)

    def test_track_click_redirects_stream_jobs_to_landing_page(self):
        self.job.video_path = "https://watch.cloudflarestream.com/stream-video-123"
        self.job.save(update_fields=["video_path"])
        token = build_tracking_token(tracking_id=self.tracking.id)

        response = self.client.get(reverse("track_click"), {"t": token})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"http://127.0.0.1:8000{reverse('video_landing', args=[self.job.id])}",
        )

    def test_video_landing_renders_post_video_cta_for_campaign_linked_job(self):
        self.job.video_path = "https://customer-example.cloudflarestream.com/stream-video-123/watch"
        self.job.save(update_fields=["video_path"])
        self.campaign.cta_url = "https://example.com/donate-again"
        self.campaign.cta_label = "Donate Again"
        self.campaign.save(update_fields=["cta_url", "cta_label"])

        response = self.client.get(reverse("video_landing", args=[self.job.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'src="https://customer-example.cloudflarestream.com/stream-video-123/iframe"',
            html=False,
        )
        self.assertContains(response, 'id="ctaOverlay"', html=False)
        self.assertContains(response, "Donate Again")
        self.assertContains(response, "embed.cloudflarestream.com/embed/sdk.latest.js")
        self.assertNotContains(response, '<video id="mainVideo"', html=False)

    def test_video_landing_omits_post_video_cta_without_job_campaign_link(self):
        self.campaign.cta_url = "https://example.com/donate-again"
        self.campaign.cta_label = "Donate Again"
        self.campaign.save(update_fields=["cta_url", "cta_label"])
        job_without_campaign = DonationJob.objects.create(
            charity=self.charity,
            donation_batch=self.batch,
            donor_name="No Campaign Donor",
            email="nocampaign@example.com",
            donation_amount=Decimal("10.00"),
            status="success",
            video_path="https://customer-example.cloudflarestream.com/orphan-stream-123/watch",
        )

        response = self.client.get(reverse("video_landing", args=[job_without_campaign.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="ctaOverlay"', html=False)
        self.assertNotContains(response, 'id="ctaBtn"', html=False)

    def test_video_landing_redirects_non_stream_video_urls(self):
        response = self.client.get(reverse("video_landing", args=[self.job.id]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://cdn.example.com/video.mp4")


class CloudflareStreamUrlTests(TestCase):
    def test_extract_stream_video_id_reads_watch_url(self):
        self.assertEqual(
            extract_stream_video_id("https://watch.cloudflarestream.com/stream-video-123"),
            "stream-video-123",
        )


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class CampaignAdminCSVUploadTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.client.force_login(self.superuser)

        today = date.today()
        self.charity = Charity.objects.create(
            charity_name="Admin Charity",
            contact_email="admin-charity@example.com",
        )
        self.other_charity = Charity.objects.create(
            charity_name="Other Charity",
            contact_email="other-charity@example.com",
        )
        self.campaign = Campaign.objects.create(
            name="Admin Upload Campaign",
            charity=self.charity,
            campaign_code="ADM-001",
            campaign_start=today,
            campaign_end=today,
            campaign_mode=Campaign.CampaignMode.VDM,
        )
        self.other_campaign = Campaign.objects.create(
            name="Other Campaign",
            charity=self.other_charity,
            campaign_code="OTH-001",
            campaign_start=today,
            campaign_end=today,
            campaign_mode=Campaign.CampaignMode.VDM,
        )

    def test_campaign_change_page_shows_upload_link(self):
        response = self.client.get(
            reverse("admin:charity_campaign_change", args=[self.campaign.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("admin:charity_campaign_upload_csv", args=[self.campaign.pk]),
        )

    @patch("charity.utils.batch_uploads.batch_process_csv.apply_async")
    def test_admin_upload_creates_campaign_batch_and_enqueues_processing(self, mock_apply_async):
        upload = SimpleUploadedFile(
            "supporters.csv",
            b"Name,Amount,Email\nJane Doe,25,jane@example.com\n",
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("admin:charity_campaign_upload_csv", args=[self.campaign.pk]),
            {"csv_file": upload},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "accepted for campaign")

        batch = DonationBatch.objects.get(campaign=self.campaign)
        self.assertEqual(batch.charity, self.charity)
        self.assertEqual(batch.campaign_name, self.campaign.name)
        self.assertTrue(batch.csv_filename.startswith("uploads/csv/"))
        self.assertEqual(DonationBatch.objects.filter(campaign=self.other_campaign).count(), 0)
        mock_apply_async.assert_called_once_with(args=(batch.id,))

    def test_admin_upload_requires_file(self):
        response = self.client.post(
            reverse("admin:charity_campaign_upload_csv", args=[self.campaign.pk]),
            {},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertEqual(DonationBatch.objects.filter(campaign=self.campaign).count(), 0)


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class CharityAdminLogoTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin-logo",
            email="admin-logo@example.com",
            password="password123",
        )
        self.client.force_login(self.superuser)
        self.charity = Charity.objects.create(
            charity_name="Admin Logo Charity",
            contact_email="logo@example.com",
        )
        today = date.today()
        self.campaign = Campaign.objects.create(
            name="Admin Logo Campaign",
            charity=self.charity,
            campaign_code="LOGO-001",
            campaign_start=today,
            campaign_end=today,
            campaign_mode=Campaign.CampaignMode.VDM,
        )

    def test_charity_change_page_shows_logo_upload_field(self):
        response = self.client.get(reverse("admin:charity_charity_change", args=[self.charity.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="logo"', html=False)

    @patch("charity.admin.resolve_storage_video_url")
    def test_charity_admin_logo_preview_uses_resolved_storage_url(self, mock_resolve_storage_url):
        from charity.admin import CharityAdmin

        self.charity.logo = build_test_image_upload("admin-logo.gif")
        self.charity.save(update_fields=["logo"])
        mock_resolve_storage_url.return_value = "https://assets.example.com/charity-logo.gif"

        model_admin = CharityAdmin(Charity, admin.site)
        preview_html = str(model_admin.logo_preview(self.charity))

        self.assertIn("https://assets.example.com/charity-logo.gif", preview_html)
        self.assertIn("<img", preview_html)

    @patch("charity.admin.default_storage.delete")
    def test_charity_admin_replacing_logo_deletes_previous_file(self, mock_delete):
        from charity.admin import CharityAdmin

        self.charity.logo = build_test_image_upload("old-admin-logo.gif")
        self.charity.save(update_fields=["logo"])
        previous_logo_name = self.charity.logo.name

        self.charity.logo = build_test_image_upload("new-admin-logo.gif")
        model_admin = CharityAdmin(Charity, admin.site)
        request = self.client.request().wsgi_request
        request.user = self.superuser

        model_admin.save_model(request, self.charity, form=None, change=True)

        mock_delete.assert_called_once_with(previous_logo_name)

    @patch(
        "charity.admin.resolve_storage_video_url",
        return_value=(
            "https://pub-adfa32dd72a346b18b40fbc2bf8fb6fc.r2.dev/"
            "charities/charity_1/campaign_overrides/admin-thumb.gif"
        ),
    )
    def test_campaign_admin_form_uses_public_media_url_for_thumbnail_preview(
        self,
        mock_resolve_storage_url,
    ):
        from charity.admin import CampaignAdminForm

        thumbnail = SimpleUploadedFile(
            "admin-thumb.gif",
            (
                b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
                b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
                b"\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )
        self.campaign.email_thumbnail = thumbnail
        self.campaign.save(update_fields=["email_thumbnail"])
        self.campaign.refresh_from_db()

        form = CampaignAdminForm(instance=self.campaign)
        widget_context = form.fields["email_thumbnail"].widget.get_context(
            "email_thumbnail",
            self.campaign.email_thumbnail,
            {},
        )

        self.assertEqual(
            widget_context["widget"]["value"].url,
            "https://pub-adfa32dd72a346b18b40fbc2bf8fb6fc.r2.dev/"
            "charities/charity_1/campaign_overrides/admin-thumb.gif",
        )
        self.assertEqual(
            widget_context["widget"]["public_url"],
            "https://pub-adfa32dd72a346b18b40fbc2bf8fb6fc.r2.dev/"
            "charities/charity_1/campaign_overrides/admin-thumb.gif",
        )
        self.assertTrue(widget_context["widget"]["is_image_preview"])
        self.assertFalse(widget_context["widget"]["missing_file"])
        mock_resolve_storage_url.assert_called_once_with(
            storage_path=self.campaign.email_thumbnail.name,
            server_url="http://127.0.0.1:8000",
        )

    @patch("charity.admin.resolve_storage_video_url", return_value="")
    def test_campaign_admin_form_marks_missing_thumbnail_files(
        self,
        mock_resolve_storage_url,
    ):
        from charity.admin import CampaignAdminForm

        thumbnail = SimpleUploadedFile(
            "admin-thumb.jpg",
            b"fake-image-bytes",
            content_type="image/jpeg",
        )
        self.campaign.email_thumbnail = thumbnail
        self.campaign.save(update_fields=["email_thumbnail"])
        self.campaign.refresh_from_db()

        form = CampaignAdminForm(instance=self.campaign)
        widget_context = form.fields["email_thumbnail"].widget.get_context(
            "email_thumbnail",
            self.campaign.email_thumbnail,
            {},
        )

        self.assertEqual(
            widget_context["widget"]["display_name"],
            self.campaign.email_thumbnail.name,
        )
        self.assertEqual(widget_context["widget"]["public_url"], "")
        self.assertTrue(widget_context["widget"]["is_image_preview"])
        self.assertTrue(widget_context["widget"]["missing_file"])
        mock_resolve_storage_url.assert_called_once_with(
            storage_path=self.campaign.email_thumbnail.name,
            server_url="http://127.0.0.1:8000",
        )


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
