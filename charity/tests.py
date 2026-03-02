from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from charity.models import Charity, DonationBatch, DonationJob, Campaign
from unittest.mock import patch
from datetime import date
import uuid

class MultiTenantIsolationTests(TestCase):
    def setUp(self):
        # Create two users/charities
        self.user_a = User.objects.create_user(username='charity_a', password='password')
        self.charity_a = Charity.objects.create(client_name="Charity A", contact_email="a@test.com")
        
        self.user_b = User.objects.create_user(username='charity_b', password='password')
        self.charity_b = Charity.objects.create(client_name="Charity B", contact_email="b@test.com")
        
        self.client = Client()
        
        # Create data for Charity A
        self.batch_a = DonationBatch.objects.create(charity=self.charity_a, batch_number=1)
        self.job_a = DonationJob.objects.create(
            donation_batch=self.batch_a, 
            donor_name="Donor A", 
            email="a@test.com", 
            donation_amount="10"
        )
        
        # Create data for Charity B
        self.batch_b = DonationBatch.objects.create(charity=self.charity_b, batch_number=2)
        self.job_b = DonationJob.objects.create(
            donation_batch=self.batch_b, 
            donor_name="Donor B", 
            email="b@test.com", 
            donation_amount="20"
        )

    def test_dashboard_isolation(self):
        """Charity A should only see Charity A (Self), not Charity B"""
        self.client.login(username='charity_a', password='password')
        # Dashboards are usually restricted to members
        from charity.models import CharityMember
        CharityMember.objects.create(charity=self.charity_a, user=self.user_a, role='Admin')
        
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Charity A")
        self.assertNotContains(response, "Charity B")

class VideoProcessingIsolationTests(TestCase):
    def setUp(self):
        self.charity_a = Charity.objects.create(client_name="Charity A", contact_email="a@charity.org")
        self.charity_b = Charity.objects.create(client_name="Charity B", contact_email="b@charity.org")
        
        # Campaigns with scripts/settings replacing templates
        self.campaign_a = Campaign.objects.create(
            name="Campaign A", 
            client=self.charity_a,
            appeal_start=date.today(),
            appeal_end=date.today(),
            is_personalized=True
        )
        self.charity_a.default_voiceover_script = "Hello A {{donor_name}}"
        self.charity_a.save()
        
        self.campaign_b = Campaign.objects.create(
            name="Campaign B", 
            client=self.charity_b,
            appeal_start=date.today(),
            appeal_end=date.today(),
            is_personalized=True
        )
        self.charity_b.default_voiceover_script = "Hello B {{donor_name}}"
        self.charity_b.save()
        
        # Jobs for A
        self.batch_a = DonationBatch.objects.create(charity=self.charity_a, campaign=self.campaign_a, batch_number=1)
        self.job_a = DonationJob.objects.create(donation_batch=self.batch_a, donor_name="Donor A", email="donor@a.com", donation_amount="10", charity=self.charity_a)
        
        # Jobs for B
        self.batch_b = DonationBatch.objects.create(charity=self.charity_b, campaign=self.campaign_b, batch_number=1)
        self.job_b = DonationJob.objects.create(donation_batch=self.batch_b, donor_name="Donor B", email="donor@b.com", donation_amount="20", charity=self.charity_b)

    @patch('charity.tasks.generate_voiceover')
    @patch('charity.tasks.stitch_voice_and_overlay')
    @patch('charity.tasks.send_video_email')
    @patch('os.path.exists')
    def test_processing_isolation(self, mock_exists, mock_send, mock_stitch, mock_tts):
        """Verify that jobs for different charities use their respective templates/branding"""
        from charity.tasks import process_donation_row
        
        mock_exists.return_value = True
        mock_tts.return_value = "/tmp/tts.mp3"
        mock_stitch.return_value = ("/tmp/final.mp4", 10)
        
        # Process Job A
        process_donation_row(self.job_a.id)
        
        # Verify Job A used Script A and Sender A
        self.assertIn("Hello A Donor A", mock_tts.call_args[1]['text'])
        self.assertEqual(mock_send.call_args[1]['from_email'], "a@charity.org")
        
        # Reset mocks
        mock_tts.reset_mock()
        mock_send.reset_mock()
        
        # Process Job B
        process_donation_row(self.job_b.id)
        
        # Verify Job B used Script B and Sender B
        self.assertIn("Hello B Donor B", mock_tts.call_args[1]['text'])
        self.assertEqual(mock_send.call_args[1]['from_email'], "b@charity.org")
