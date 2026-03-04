from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from charity.models import Campaign, Charity, DonationBatch, DonationJob


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
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
)
class VideoProcessingIsolationTests(TestCase):
    def setUp(self):
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
    @patch("charity.services.video_build_service.stitch_voice_and_overlay")
    @patch("charity.tasks.send_video_email")
    @patch("charity.tasks.stream_safe_upload", return_value=None)
    @patch("os.path.exists")
    def test_processing_isolation(
        self, mock_exists, mock_stream, mock_send, mock_stitch, mock_tts, mock_upload
    ):
        """Verify that jobs for different charities use their respective templates/branding"""
        from charity.tasks import (
            dispatch_email_for_job,
            generate_video_for_job,
            validate_and_prep_job,
        )

        mock_exists.return_value = True
        mock_tts.return_value = "/tmp/tts.mp3"
        mock_stitch.return_value = ("/tmp/final.mp4", 10)

        # Process Job A through all 3 stages
        ctx = validate_and_prep_job.run(self.job_a.id)  # type: ignore[attr-defined]
        ctx = generate_video_for_job.run(ctx)  # type: ignore[attr-defined]
        dispatch_email_for_job.run(ctx)  # type: ignore[attr-defined]

        # Verify Job A used Script A and Sender A
        self.assertIn("Hello A Donor A", mock_tts.call_args[1]["text"])
        self.assertEqual(mock_send.call_args[1]["from_email"], "a@charity.org")

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
