import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from charity.models import (
    Campaign,
    Charity,
    CharityMember,
    Donation,
    DonationBatch,
    DonationJob,
    Donor,
    Invoice,
    UnsubscribedUser,
    VideoSendLog,
)


class MultiTenancyIsolationTest(TestCase):
    def setUp(self):
        # Create Charity A + User A
        self.charity_a = Charity.objects.create(
            charity_name="Charity A", contact_email="a@test.com"
        )
        self.user_a = User.objects.create_user(username="user_a", password="password123")
        CharityMember.objects.create(charity=self.charity_a, user=self.user_a, role="Admin")

        # Create Charity B + User B
        self.charity_b = Charity.objects.create(
            charity_name="Charity B", contact_email="b@test.com"
        )
        self.user_b = User.objects.create_user(username="user_b", password="password123")
        CharityMember.objects.create(charity=self.charity_b, user=self.user_b, role="Admin")

        # Create Superuser
        self.superuser = User.objects.create_superuser(
            username="admin", password="password123", email="admin@example.com"
        )

        from datetime import timedelta

        today = timezone.now().date()
        self.today = today

        # Create Data for Charity A
        self.batch_a = DonationBatch.objects.create(charity=self.charity_a, batch_number=1)
        self.job_a = DonationJob.objects.create(
            donation_batch=self.batch_a,
            donor_name="Donor A",
            email="donor_a@example.com",
            donation_amount=Decimal("10.00"),
            status="success",
            charity=self.charity_a,
        )
        self.invoice_a = Invoice.objects.create(
            charity=self.charity_a,
            invoice_number="INV-A-1",
            amount=100.00,
            issue_date=today,
            due_date=today + timedelta(days=30),
        )

        # Create Data for Charity B
        self.batch_b = DonationBatch.objects.create(charity=self.charity_b, batch_number=1)
        self.job_b = DonationJob.objects.create(
            donation_batch=self.batch_b,
            donor_name="Donor B",
            email="donor_b@example.com",
            donation_amount=Decimal("20.00"),
            status="success",
            charity=self.charity_b,
        )
        self.invoice_b = Invoice.objects.create(
            charity=self.charity_b,
            invoice_number="INV-B-1",
            amount=200.00,
            issue_date=today,
            due_date=today + timedelta(days=30),
        )
        self.campaign_a = Campaign.objects.create(
            name="Campaign A",
            charity=self.charity_a,
            campaign_code="A-001",
            campaign_start=today,
            campaign_end=today,
            campaign_mode=Campaign.CampaignMode.THANK_YOU_PERSONALIZED,
        )
        self.campaign_b = Campaign.objects.create(
            name="Campaign B",
            charity=self.charity_b,
            campaign_code="B-001",
            campaign_start=today,
            campaign_end=today,
            campaign_mode=Campaign.CampaignMode.THANK_YOU_PERSONALIZED,
        )

        donated_at = timezone.now()
        self.donor_a = Donor.objects.create(
            charity=self.charity_a,
            email="donor_a@example.com",
            full_name="Donor A",
        )
        self.donor_b = Donor.objects.create(
            charity=self.charity_b,
            email="donor_b@example.com",
            full_name="Donor B",
        )
        self.donation_a = Donation.objects.create(
            donor=self.donor_a,
            charity=self.charity_a,
            amount=Decimal("10.00"),
            donated_at=donated_at,
            campaign_type="THANK_YOU",
            source="CSV",
        )
        self.donation_b = Donation.objects.create(
            donor=self.donor_b,
            charity=self.charity_b,
            amount=Decimal("20.00"),
            donated_at=donated_at,
            campaign_type="THANK_YOU",
            source="API",
        )
        VideoSendLog.objects.create(
            charity=self.charity_a,
            donor=self.donor_a,
            donation=self.donation_a,
            campaign=self.campaign_a,
            campaign_type="THANK_YOU",
            send_kind=VideoSendLog.SendKind.PERSONALIZED,
            status=VideoSendLog.Status.SENT,
            recipient_email=self.donor_a.email,
            stream_playback_url="https://watch.example.com/a",
        )
        VideoSendLog.objects.create(
            charity=self.charity_b,
            donor=self.donor_b,
            donation=self.donation_b,
            campaign=self.campaign_b,
            campaign_type="THANK_YOU",
            send_kind=VideoSendLog.SendKind.PERSONALIZED,
            status=VideoSendLog.Status.FAILED,
            recipient_email=self.donor_b.email,
            error_message="send failed",
        )

    def test_dashboard_isolation(self):
        """Verify User A cannot see Charity B's data on dashboard."""
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        # Should see Charity A
        content = response.content.decode()
        # The header context badge renders charity name in uppercase
        self.assertIn("CHARITY A", content)
        # Should NOT see Charity B
        self.assertNotIn("CHARITY B", content)

    def test_invoice_detail_isolation(self):
        """Verify User A cannot access Charity B's invoice detail page."""
        self.client.login(username="user_a", password="password123")
        # Attempt to access Invoice B
        response = self.client.get(
            reverse("invoice_detail", kwargs={"invoice_id": self.invoice_b.id})
        )
        # Based on refactored view, should return 404
        self.assertEqual(response.status_code, 404)

    def test_batch_detail_isolation(self):
        """Verify User A cannot access Charity B's batch detail page."""
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse("batch_detail", kwargs={"batch_id": self.batch_b.id}))
        self.assertEqual(response.status_code, 404)

    def test_superuser_context_switching(self):
        """Verify Super Admin can switch context and see correct data."""
        self.client.login(username="admin", password="password123")

        # Initial: Global View (no charity context)
        response = self.client.get(reverse("dashboard"))
        content = response.content.decode()
        self.assertIn("GLOBAL VIEW", content)

        # Switch to Charity A
        self.client.get(reverse("switch_charity", kwargs={"charity_id": self.charity_a.id}))
        response = self.client.get(reverse("dashboard"))
        content = response.content.decode()
        self.assertIn("CHARITY A", content)
        self.assertNotIn("CHARITY B", content)

        # Clear context
        self.client.get(reverse("clear_charity_context"))
        response = self.client.get(reverse("dashboard"))
        content = response.content.decode()
        self.assertIn("GLOBAL VIEW", content)

    def test_unsubscribe_isolation(self):
        """Verify unsubscriptions are scoped to charity."""
        # Unsubscribe Donor A from Charity A
        UnsubscribedUser.objects.create(charity=self.charity_a, email="donor_a@example.com")

        # Check in Charity A context
        self.assertTrue(UnsubscribedUser.is_unsubscribed("donor_a@example.com", self.charity_a))
        # Check in Charity B context (should NOT be unsubscribed)
        self.assertFalse(UnsubscribedUser.is_unsubscribed("donor_a@example.com", self.charity_b))

    def test_logs_isolation(self):
        """Verify User A only sees logs for Charity A."""
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse("logs"))
        self.assertEqual(response.status_code, 200)

        # Logs view shows a table of jobs.
        # Since Charity A has 1 job, pagination shows "1 results".
        self.assertIn("of <strong>1</strong> results", response.content.decode())

        # User B should see their own 1 job
        self.client.login(username="user_b", password="password123")
        response = self.client.get(reverse("logs"))
        self.assertIn("of <strong>1</strong> results", response.content.decode())

    def test_api_ingest_rejects_cross_charity_access(self):
        self.client.login(username="user_a", password="password123")

        response = self.client.post(
            reverse("donation-ingest"),
            {
                "charity_id": self.charity_b.id,
                "donor_email": "intruder@example.com",
                "donor_name": "Intruder",
                "amount": "15.00",
                "campaign_type": "THANK_YOU",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("charity_id", response.json())
        self.assertFalse(DonationJob.objects.filter(email="intruder@example.com").exists())

    def test_task_status_isolation(self):
        self.client.login(username="user_a", password="password123")

        response = self.client.get(
            reverse("task-status", kwargs={"task_id": "ignored-task-id"}),
            {"job_id": self.job_b.id},
        )

        self.assertEqual(response.status_code, 404)

    def test_campaign_report_isolation(self):
        self.client.login(username="user_a", password="password123")

        response = self.client.get(
            reverse("api_campaign_report", kwargs={"campaign_id": self.campaign_b.id})
        )

        self.assertEqual(response.status_code, 404)

    def test_send_wizard_rejects_other_campaign(self):
        self.client.login(username="user_a", password="password123")

        response = self.client.get(
            reverse("send_email_wizard"),
            {"campaign_id": str(self.campaign_b.id)},
        )

        self.assertEqual(response.status_code, 404)

    def test_billing_create_rejects_other_charity(self):
        self.client.login(username="user_a", password="password123")

        response = self.client.post(
            reverse("api_billing_create"),
            data=json.dumps({"charity_id": self.charity_b.id, "items": []}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_billing_create_uses_charity_additional_emails(self):
        self.charity_a.additional_emails = "finance@a.test,ops@a.test"
        self.charity_a.save(update_fields=["additional_emails"])
        self.client.login(username="user_a", password="password123")

        response = self.client.post(
            reverse("api_billing_create"),
            data=json.dumps({"charity_id": self.charity_a.id, "items": []}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        invoice = Invoice.objects.get(id=response.json()["invoice_id"])
        self.assertEqual(invoice.additional_billing_emails, "finance@a.test,ops@a.test")

    def test_video_landing_route_uses_integer_job_ids(self):
        self.job_a.video_path = "https://customer-example.cloudflarestream.com/video-a-123/watch"
        self.job_a.save(update_fields=["video_path"])

        response = self.client.get(reverse("video_landing", kwargs={"job_id": self.job_a.id}))

        self.assertEqual(response.status_code, 200)

    def test_donors_list_isolation(self):
        self.client.login(username="user_a", password="password123")

        response = self.client.get(reverse("donors"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "donor_a@example.com")
        self.assertNotContains(response, "donor_b@example.com")

    def test_donor_detail_isolation(self):
        self.client.login(username="user_a", password="password123")

        allowed = self.client.get(reverse("donor_detail", kwargs={"donor_id": self.donor_a.id}))
        blocked = self.client.get(reverse("donor_detail", kwargs={"donor_id": self.donor_b.id}))

        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "GBP 10.00")
        self.assertEqual(blocked.status_code, 404)

    def test_donations_list_isolation(self):
        self.client.login(username="user_a", password="password123")

        response = self.client.get(reverse("donations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "donor_a@example.com")
        self.assertNotContains(response, "donor_b@example.com")
        self.assertContains(response, "CSV")
        self.assertNotContains(response, "send failed")

    def test_donors_view_requires_active_charity_for_superuser(self):
        self.client.login(username="admin", password="password123")

        response = self.client.get(reverse("donors"))

        self.assertRedirects(response, reverse("dashboard"))
