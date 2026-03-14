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
    DonationBatch,
    DonationJob,
    EmailTracking,
    Invoice,
    UnsubscribedUser,
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
        EmailTracking.objects.create(
            campaign=self.campaign_a,
            batch=self.batch_a,
            job=self.job_a,
            user_id=self.job_a.id,
            campaign_type="THANK_YOU",
            opened=True,
        )
        EmailTracking.objects.create(
            campaign=self.campaign_b,
            batch=self.batch_b,
            job=self.job_b,
            user_id=self.job_b.id,
            campaign_type="THANK_YOU",
            clicked=True,
        )

    def test_dashboard_isolation(self):
        """Verify legacy dashboard URLs land on analytics without cross-charity leakage."""
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse("dashboard"), follow=True)
        self.assertRedirects(response, reverse("analytics_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Analytics & Reports")
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
        response = self.client.get(reverse("dashboard"), follow=True)
        self.assertRedirects(response, reverse("analytics_home"))
        content = response.content.decode()
        self.assertIn("Analytics & Reports", content)
        self.assertIn("GLOBAL VIEW", content)

        # Switch to Charity A
        self.client.get(reverse("switch_charity", kwargs={"charity_id": self.charity_a.id}))
        response = self.client.get(reverse("dashboard"), follow=True)
        self.assertRedirects(response, reverse("analytics_home"))
        content = response.content.decode()
        self.assertIn("CHARITY A", content)
        self.assertNotIn("CHARITY B", content)

        # Clear context
        self.client.get(reverse("clear_charity_context"))
        response = self.client.get(reverse("dashboard"), follow=True)
        self.assertRedirects(response, reverse("analytics_home"))
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

    def test_batch_tracking_report_isolation(self):
        self.client.login(username="user_a", password="password123")

        allowed = self.client.get(
            reverse("batch_tracking_report", kwargs={"batch_id": self.batch_a.id})
        )
        blocked = self.client.get(
            reverse("batch_tracking_report", kwargs={"batch_id": self.batch_b.id})
        )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["total_sent"], 1)
        self.assertEqual(allowed.json()["opened_count"], 1)
        self.assertEqual(blocked.status_code, 404)

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
