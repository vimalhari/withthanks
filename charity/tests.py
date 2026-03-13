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
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from charity.models import (
    Campaign,
    Charity,
    CharityMember,
    DonationBatch,
    DonationJob,
    EmailTracking,
)
from charity.utils.tracking_security import build_tracking_token


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
            video_mode=Campaign.VideoMode.PERSONALIZED,
            voiceover_script="Hello A {{donor_name}}",
        )
        # Provide a fake base video path (os.path.exists is mocked True in tests)
        Campaign.objects.filter(pk=self.campaign_a.pk).update(base_video="test/fake_video_a.mp4")

        self.campaign_b = Campaign.objects.create(
            name="Campaign B",
            charity=self.charity_b,
            campaign_start=date.today(),
            campaign_end=date.today(),
            video_mode=Campaign.VideoMode.PERSONALIZED,
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
        self.assertEqual(mock_send.call_args[1]["video_url"], "https://r2.example.com/v.mp4")

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
        self.assertEqual(mock_send.call_args[1]["video_url"], "https://r2.example.com/v.mp4")

    @patch("charity.tasks.send_video_email")
    @patch("charity.services.video_pipeline_service.stream_safe_upload", return_value=None)
    def test_vdm_falls_back_to_public_storage_url_when_stream_unavailable(
        self,
        mock_stream,
        mock_send,
    ):
        """VDM should send a public media URL, not the worker's /tmp path."""
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(charity_video="test/fake_video_a.mp4")
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
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        self.assertEqual(
            mock_send.call_args[1]["video_url"],
            "http://127.0.0.1:8000/media/test/fake_video_a.mp4",
        )
        self.assertIn("Dear VDM Donor,", mock_send.call_args[1]["html"])
        vdm_job.refresh_from_db()
        self.assertEqual(vdm_job.video_path, "http://127.0.0.1:8000/media/test/fake_video_a.mp4")

    @patch("charity.tasks.send_video_email")
    @patch("charity.services.video_pipeline_service.stream_safe_upload", return_value=None)
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
            vdm_email_body=(
                "Welcome to {{ campaign_name }} from {{ charity_name }}.\n\n"
                "We made this update for {{ donor_name }}."
            ),
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(charity_video="test/fake_video_a.mp4")
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

        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn("Welcome to Custom Copy Campaign from", html)
        self.assertIn("We made this update for Jane.", html)
        self.assertNotIn("We are excited to share some amazing updates with you!", html)

    @patch("charity.tasks.send_video_email")
    @patch("charity.services.video_pipeline_service.stream_safe_upload", return_value=None)
    def test_vdm_uses_campaign_email_thumbnail_as_clickable_image(
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
            email_thumbnail=thumbnail,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(charity_video="test/fake_video_a.mp4")
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

        mock_send.return_value = {"id": "test-resend-id"}

        ctx = validate_and_prep_job.run(vdm_job.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        html = mock_send.call_args[1]["html"]
        self.assertIn('src="http://127.0.0.1:8000/media/', html)
        self.assertIn("vdm-thumb", html)
        self.assertIn('href="http://127.0.0.1:8000/charity/track/click/?t=', html)

    @patch("charity.tasks.send_video_email")
    @patch("charity.services.video_pipeline_service.stream_safe_upload", return_value=None)
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(charity_video="test/fake_video_a.mp4")
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
    @patch("charity.tasks.stream_safe_upload", return_value=None)
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
    @patch("charity.services.video_pipeline_service.stream_safe_upload", return_value=None)
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(charity_video="test/fake_video_a.mp4")
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(charity_video="test/fake_video_a.mp4")

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
        self.assertEqual(jobs.first().campaign, vdm_campaign)
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
            status="active",
            campaign_type=Campaign.CampaignType.VDM,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.TEMPLATE,
        )
        Campaign.objects.filter(pk=vdm_campaign.pk).update(charity_video="test/fake_video_a.mp4")

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
            status="active",
            campaign_type=Campaign.CampaignType.THANK_YOU,
            input_source=Campaign.InputSource.CSV,
            video_mode=Campaign.VideoMode.PERSONALIZED,
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
                "campaign_type": Campaign.CampaignType.VDM,
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
                        "campaign_type": Campaign.CampaignType.VDM,
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
