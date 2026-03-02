from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from charity.models import Charity, CharityMember, DonationBatch, DonationJob, UnsubscribedUser, Invoice

class MultiTenancyIsolationTest(TestCase):
    def setUp(self):
        # Create Charity A + User A
        self.charity_a = Charity.objects.create(client_name="Charity A", contact_email="a@test.com")
        self.user_a = User.objects.create_user(username="user_a", password="password123")
        CharityMember.objects.create(charity=self.charity_a, user=self.user_a, role="Admin")
        
        # Create Charity B + User B
        self.charity_b = Charity.objects.create(client_name="Charity B", contact_email="b@test.com")
        self.user_b = User.objects.create_user(username="user_b", password="password123")
        CharityMember.objects.create(charity=self.charity_b, user=self.user_b, role="Admin")
        
        # Create Superuser
        self.superuser = User.objects.create_superuser(username="admin", password="password123", email="admin@example.com")
        
        from django.utils import timezone
        from datetime import timedelta
        today = timezone.now().date()
        
        # Create Data for Charity A
        self.batch_a = DonationBatch.objects.create(charity=self.charity_a, batch_number=1)
        self.job_a = DonationJob.objects.create(
            donation_batch=self.batch_a, 
            donor_name="Donor A", 
            email="donor_a@example.com", 
            donation_amount="10.00",
            status="success",
            charity=self.charity_a
        )
        self.invoice_a = Invoice.objects.create(
            charity=self.charity_a, 
            invoice_number="INV-A-1", 
            amount=100.00,
            issue_date=today,
            due_date=today + timedelta(days=30)
        )
        
        # Create Data for Charity B
        self.batch_b = DonationBatch.objects.create(charity=self.charity_b, batch_number=1)
        self.job_b = DonationJob.objects.create(
            donation_batch=self.batch_b, 
            donor_name="Donor B", 
            email="donor_b@example.com", 
            donation_amount="20.00",
            status="success",
            charity=self.charity_b
        )
        self.invoice_b = Invoice.objects.create(
            charity=self.charity_b, 
            invoice_number="INV-B-1", 
            amount=200.00,
            issue_date=today,
            due_date=today + timedelta(days=30)
        )

    def test_dashboard_isolation(self):
        """Verify User A cannot see Charity B's data on dashboard."""
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        # Should see Charity A
        content = response.content.decode()
        self.assertIn("Charity A", content)
        # Should NOT see Charity B
        self.assertNotIn("Charity B", content)

    def test_invoice_detail_isolation(self):
        """Verify User A cannot access Charity B's invoice detail page."""
        self.client.login(username="user_a", password="password123")
        # Attempt to access Invoice B
        response = self.client.get(reverse('invoice_detail', kwargs={'invoice_id': self.invoice_b.id}))
        # Based on refactored view, should return 404
        self.assertEqual(response.status_code, 404)

    def test_batch_detail_isolation(self):
        """Verify User A cannot access Charity B's batch detail page."""
        self.client.login(username="user_a", password="password123")
        response = self.client.get(reverse('batch_detail', kwargs={'batch_id': self.batch_b.id}))
        self.assertEqual(response.status_code, 404)

    def test_superuser_context_switching(self):
        """Verify Super Admin can switch context and see correct data."""
        self.client.login(username="admin", password="password123")
        
        # Initial: Global View
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode()
        self.assertIn("Charity A", content)
        self.assertIn("Charity B", content)
        
        # Switch to Charity A
        self.client.get(reverse('switch_client', kwargs={'charity_id': self.charity_a.id}))
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode()
        self.assertIn("Charity A", content)
        self.assertNotIn("Charity B", content)
        
        # Clear context
        self.client.get(reverse('clear_client_context'))
        response = self.client.get(reverse('dashboard'))
        content = response.content.decode()
        self.assertIn("Charity A", content)
        self.assertIn("Charity B", content)

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
        response = self.client.get(reverse('logs'))
        self.assertEqual(response.status_code, 200)
        
        # Logs view shows a table of jobs. 
        # Since Charity A has 1 job, start_index should be 1.
        self.assertIn("Showing 1 to 1 of 1 results", response.content.decode())
        
        # User B should see their own 1 job
        self.client.login(username="user_b", password="password123")
        response = self.client.get(reverse('logs'))
        self.assertIn("Showing 1 to 1 of 1 results", response.content.decode())
