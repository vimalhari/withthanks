import uuid
import os
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_delete
from django.dispatch import receiver
from charity.utils.media_utils import get_client_media_path


# Create your models here.
class Charity(models.Model):
    # CLIENT MODEL (MINIMAL & FINAL)
    client_name = models.CharField(max_length=255)
    contact_email = models.EmailField()
    organization_name = models.CharField(max_length=255)
    default_template_video = models.FileField(upload_to=get_client_media_path, blank=True, null=True, help_text="fallback MP4")
    gratitude_card = models.FileField(upload_to=get_client_media_path, blank=True, null=True, help_text="Gratitude card (Video or Image)")
    
    # Billing Information
    billing_email = models.EmailField(blank=True, null=True, help_text="Override contact email for invoices")
    billing_address = models.TextField(blank=True, null=True, help_text="Specific billing address for invoices")
    
    # Blackbaud Integration
    blackbaud_client_id = models.CharField(max_length=255, blank=True, null=True, help_text="Blackbaud SKY API Client ID")
    blackbaud_client_secret = models.CharField(max_length=255, blank=True, null=True, help_text="Blackbaud SKY API Client Secret")
    blackbaud_enabled = models.BooleanField(default=False, help_text="Enable Raiser's Edge integration")
    
    # Defaults used by processing pipeline
    default_voiceover_script = models.TextField(blank=True, help_text="Default script with placeholders {{donor_name}}, {{donation_amount}}, {{organization_name}}")
    default_voice_id = models.CharField(max_length=128, blank=True, help_text="Default ElevenLabs voice ID")
    
    # User Access
    members = models.ManyToManyField(User, through='CharityMember', related_name='charity_memberships', blank=True)
    
    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    company_number = models.CharField(max_length=50, blank=True, null=True)
    
    # Physical Address
    address_line_1 = models.CharField(max_length=255, blank=True, null=True)
    address_line_2 = models.CharField(max_length=255, blank=True, null=True)
    county = models.CharField(max_length=100, blank=True, null=True)
    postcode = models.CharField(max_length=20, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.client_name

    # Backward compatibility properties
    @property
    def name(self):
        return self.client_name
    
    @property
    def sender_email(self):
        return self.contact_email

class CharityMember(models.Model):
    ROLE_CHOICES = [
        ('Admin', 'Admin'),
        ('Member', 'Member'),
        ('Viewer', 'Viewer'),
    ]
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('PENDING', 'Pending'),
    ]
    
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='Member')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('charity', 'user')

    def __str__(self):
        return f"{self.user.username} - {self.charity.name} ({self.role})"

class InvoiceService(models.Model):
    """Catalog of billable services"""
    CATEGORY_CHOICES = [
        ('setup', 'Set Up & Management'),
        ('production', 'Video Production'),
        ('gratitude', 'Gratitude Cards'),
        ('postage', 'Postage & Printing'),
        ('other', 'Other'),
    ]
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    is_active = models.BooleanField(default=True)
    
    # Tiered pricing support (optional for now, can be JSON or simple fields)
    is_tiered = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (${self.unit_price})"

class Invoice(models.Model):
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Sent', 'Sent'),
        ('Paid', 'Paid'),
        ('Overdue', 'Overdue'),
        ('Void', 'Void'),
    ]
    
    INVOICE_TYPE_CHOICES = [
        ('campaign_wise', 'Campaign Wise'),
        ('single_batch', 'Single Batch'),
        ('multiple_batches', 'Multiple Batches'),
        ('date_range', 'Date Range'),
    ]
    
    PRICING_TIER_CHOICES = [
        ('standard', 'Standard'),
        ('premium', 'Premium'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name='invoices')
    campaign = models.ForeignKey('Campaign', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    invoice_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    issue_date = models.DateField()
    due_date = models.DateField()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # NEW FIELDS for batch-based billing
    invoice_type = models.CharField(
        max_length=20,
        choices=INVOICE_TYPE_CHOICES,
        default='single_batch'
    )
    
    # Pricing fields
    pricing_tier = models.CharField(max_length=20, choices=PRICING_TIER_CHOICES, default='standard')
    campaign_volume = models.PositiveIntegerField(default=0)
    price_per_video = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    price_per_batch = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    flat_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=20.00) # Default to 20% as per UI screenshot
    
    # Calculated totals (stored for performance)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Metrics snapshot (from batches at time of invoice creation)
    total_batches = models.PositiveIntegerField(default=0)
    total_videos = models.PositiveIntegerField(default=0)
    total_views = models.PositiveIntegerField(default=0)
    total_clicks = models.PositiveIntegerField(default=0)
    total_unsubscribes = models.PositiveIntegerField(default=0)
    
    # Date range (if invoice_type is 'date_range')
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    
    # Billing contact
    billing_email = models.EmailField(blank=True)
    billing_address = models.TextField(blank=True)
    
    # Additional metadata
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issue_date']

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.charity.name}"
    
    def calculate_totals(self):
        """Recalculates totals based on line items"""
        from django.db.models import Sum
        # Sum from line items
        subtotal = self.line_items.aggregate(sum=Sum('total_amount'))['sum'] or 0
        self.subtotal = subtotal
        
        # Calculate discount
        if self.discount_percent > 0:
            self.discount_amount = (self.subtotal * self.discount_percent) / 100
        else:
            self.discount_amount = 0
            
        # Tax
        taxable_amount = self.subtotal - self.discount_amount
        if self.tax_percent > 0:
            self.tax_amount = (taxable_amount * self.tax_percent) / 100
        else:
            self.tax_amount = 0
            
        self.amount = taxable_amount + self.tax_amount
        self.save()
        
        return self.amount
    
    def generate_invoice_number(self):
        """Auto-generate invoice number: INV-YYYY-NNNN"""
        from datetime import datetime
        year = datetime.now().year
        
        # Get the last invoice number for this year
        last_invoice = Invoice.objects.filter(
            invoice_number__startswith=f'INV-{year}-'
        ).order_by('-invoice_number').first()
        
        if last_invoice:
            # Extract the sequence number and increment
            last_seq = int(last_invoice.invoice_number.split('-')[-1])
            new_seq = last_seq + 1
        else:
            new_seq = 1
        
        self.invoice_number = f'INV-{year}-{new_seq:04d}'
        return self.invoice_number


class InvoiceLineItem(models.Model):
    """Individual line items on an invoice"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    service = models.ForeignKey(InvoiceService, on_delete=models.SET_NULL, null=True, blank=True)
    
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1.00)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Metadata for linking back to source (e.g. {batch_id: 123})
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def save(self, *args, **kwargs):
        self.total_amount = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.description} ({self.invoice.invoice_number})"


class InvoiceBatch(models.Model):
    """Links invoices to batches with metrics snapshot"""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='invoice_batches')
    batch = models.ForeignKey('DonationBatch', on_delete=models.PROTECT, related_name='invoices')
    
    # Snapshot of batch metrics at invoice creation time
    videos_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    clicks_count = models.PositiveIntegerField(default=0)
    unsubscribes_count = models.PositiveIntegerField(default=0)
    
    # Campaign name for display
    campaign_name = models.CharField(max_length=255, blank=True)
    
    # Line item pricing
    line_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    class Meta:
        unique_together = ('invoice', 'batch')
        ordering = ['batch__created_at']
    
    def __str__(self):
        return f"Invoice {self.invoice.invoice_number} - Batch #{self.batch.batch_number}"
    


class DonationBatch(models.Model):
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name='batches', null=True, blank=True)
    campaign = models.ForeignKey('Campaign', on_delete=models.SET_NULL, null=True, blank=True, related_name='batches')
    media_type = models.CharField(max_length=20, choices=[('video', 'Video'), ('image', 'Image')], default='video')
    campaign_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    csv_filename = models.CharField(max_length=255, blank=True)
    batch_number = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Batch #{self.batch_number} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @classmethod
    def get_next_batch_number(cls, charity):
        last = cls.objects.filter(charity=charity).order_by('id').last()
        if not last:
            # Fallback to order by batch_number if id ordering isn't certain
            last = cls.objects.filter(charity=charity).order_by('batch_number').last()
        return last.batch_number + 1 if last else 1

    @property
    def total_records(self):
        return self.jobs.count()

    @property
    def success_count(self):
        return self.jobs.filter(status='success').count()

    @property
    def failed_count(self):
        return self.jobs.filter(status='failed').count()

    @property
    def pending_count(self):
        return self.jobs.filter(status__in=['pending', 'processing']).count()

    @property
    def upload_type(self):
        if self.csv_filename and "manual_entry.csv" not in self.csv_filename:
            return "CSV"
        return "Manual"

    @property
    def batch_status_display(self):
        if self.pending_count > 0:
            return "Processing"
        if self.failed_count > 0:
            return "Completed with Errors"
        return "Completed"

    
class DonationJob(models.Model):
    # CORE FIELDS
    donor_name = models.CharField(max_length=255)
    email = models.EmailField()
    donation_amount = models.CharField(max_length=50)
    
    # REFERENCES
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name='jobs', null=True, blank=True)
    campaign = models.ForeignKey('Campaign', on_delete=models.SET_NULL, null=True, blank=True, related_name='campaign_jobs')
    donation_batch = models.ForeignKey(DonationBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs')
    
    # STATUS & TRACKING
    status = models.CharField(max_length=20, default="pending")  # pending, processing, success, failed
    video_path = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    task_id = models.CharField(max_length=128, blank=True, null=True)
    appeal_type = models.CharField(max_length=20, choices=[("WithThanks", "WithThanks"), ("VDM", "VDM")], null=True, blank=True)
    media_type_override = models.CharField(max_length=20, choices=[('video', 'Video'), ('image', 'Image')], null=True, blank=True)
    
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generation_time = models.FloatField(null=True, blank=True)
    
    # Stats
    real_views = models.PositiveIntegerField(default=0)
    fake_views = models.PositiveIntegerField(default=0)
    real_clicks = models.PositiveIntegerField(default=0)
    fake_clicks = models.PositiveIntegerField(default=0)

    # Backward compatibility properties
    @property
    def name(self):
        return self.donor_name
    
    @property
    def amount(self):
        return self.donation_amount

    @property
    def total_views(self):
        return self.real_views + self.fake_views 

    @property
    def video_url(self):
        if not self.video_path:
            return None
        # Handle absolute paths by making them relative to MEDIA_ROOT
        from django.conf import settings
        path_str = str(self.video_path)
        if os.path.isabs(path_str):
            try:
                rel_path = os.path.relpath(path_str, settings.MEDIA_ROOT)
                return os.path.join(settings.MEDIA_URL, rel_path).replace("\\", "/")
            except ValueError:
                return None
        return os.path.join(settings.MEDIA_URL, path_str).replace("\\", "/")
    
    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["email"]),
            models.Index(fields=["created_at"]),
        ]
    
    def get_status_badge_class(self):
        """Return Bootstrap badge class based on status"""
        return {
            'pending': 'warning',
            'success': 'success',
            'failed': 'danger',
            'skipped': 'secondary'
        }.get(self.status, 'secondary')
    
    def __str__(self):
        return f"Job {self.id} - {self.name} ({self.status})"

class UnsubscribedUser(models.Model):
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name='unsubscribes', null=True, blank=True)
    email = models.EmailField()  # Remove unique=True here
    reason = models.TextField(blank=True)
    unsubscribed_from_job = models.ForeignKey(
        DonationJob, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='unsubscribes_triggered',
        help_text="The donation job that triggered this unsubscribe"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, help_text="Browser user agent string")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('charity', 'email')
        verbose_name = "Unsubscribed User"
        verbose_name_plural = "Unsubscribed Users"

    def __str__(self):
        return f"{self.email} (unsubscribed from {self.charity.name if self.charity else 'Global'} on {self.created_at.strftime('%Y-%m-%d')})"
    
    @classmethod
    def is_unsubscribed(cls, email, charity):
        """Check if an email address has unsubscribed from a specific charity."""
        return cls.objects.filter(email=email, charity=charity).exists()


class ReceivedEmail(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name='received_emails', null=True, blank=True)
    sender = models.EmailField()
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"To {self.charity.name if self.charity else 'Unknown'}: {self.subject}"

# Import Analytics Models for discovery (moved to bottom to avoid circular imports during forms initialization)
from .models_analytics import EmailEvent, VideoEvent, WatchSession, UnsubscribeEvent


class PackageCode(models.Model):
    code = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.code


class Campaign(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("closed", "Closed"),
    ]
    APPEAL_TYPES = [
        ("WithThanks", "Thank you"),
        ("VDM", "Video Direct Mail (VDM)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    client = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="campaigns")
    description = models.TextField(blank=True)

    # Appeal Details
    appeal_code = models.CharField(max_length=50)
    appeal_type = models.CharField(max_length=20, choices=APPEAL_TYPES, default="WithThanks")

    appeal_start = models.DateField()
    appeal_end = models.DateField()
    
    # Financial Overview & Dates removed as per request
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    
    # NEW CAMPAIGN MEDIA ASSETS
    charity_video = models.FileField(upload_to=get_client_media_path, blank=True, null=True, help_text="Main Campaign Video (VDM Appeal)")
    gratitude_video = models.FileField(upload_to=get_client_media_path, blank=True, null=True, help_text="Gratitude Video (WithThanks Appeal)")
    
    video_template_override = models.FileField(upload_to=get_client_media_path, blank=True, null=True, help_text="Override the default template video")
    voiceover_script_override = models.TextField(blank=True, help_text="Override the default charity voiceover script")
    
    # Personalization Settings
    is_personalized = models.BooleanField(default=False, help_text="Use TTS and personalized stitching (WithThanks only)")

    # Email Settings
    from_email = models.EmailField(blank=True, null=True, help_text="Override sender email address for this campaign")

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def package_codes_list(self):
        return [pc.code for pc in self.package_codes.all()]

    @property
    def package_codes_json(self):
        import json

        return json.dumps([{"code": pc.code} for pc in self.package_codes.all()])


class CampaignField(models.Model):
    FIELD_TYPES = [
        ("text", "Text"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("number", "Number"),
        ("date", "Date"),
        ("dropdown", "Dropdown"),
        ("radio", "Radio"),
        ("checkbox", "Checkbox"),
        ("textarea", "Textarea"),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="fields")
    label = models.CharField(max_length=100)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default="text")
    required = models.BooleanField(default=False)
    options = models.JSONField(
        default=list, blank=True, help_text="Comma-separated options for dropdown/radio/checkbox"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.label} ({self.field_type}) - {self.campaign.name}"
@receiver(post_delete, sender=Charity)
def cleanup_charity_media(sender, instance, **kwargs):
    """
    Delete media files when Charity is deleted.
    Also deletes the entire client directory if possible, but safely.
    """
    if instance.logo:
        instance.logo.delete(save=False)
    if instance.thank_you_card:
        instance.thank_you_card.delete(save=False)
    # Ideally we'd remove the folder too, but standard file field delete just removes the file.
    # Given the strict structure media/clients/client_<id>/, we could try:
    # try:
    #     import shutil, os
    #     from django.conf import settings
    #     client_dir = os.path.join(settings.MEDIA_ROOT, 'clients', f'client_{instance.id}')
    #     if os.path.exists(client_dir):
    #         shutil.rmtree(client_dir)
    # except:
    #     pass



class EmailTracking(models.Model):
    """
    Tracks the lifecycle of an individual email sent to a donor.
    """
    # Relationships
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='email_tracks', null=True, blank=True)
    batch = models.ForeignKey(DonationBatch, on_delete=models.CASCADE, related_name='email_tracks', null=True, blank=True)
    job = models.ForeignKey(DonationJob, on_delete=models.CASCADE, related_name='email_tracks', null=True, blank=True)
    
    # Metadata
    user_id = models.IntegerField(help_text="Mapped to DonationJob ID for backwards compatibility URL params", null=True, blank=True)
    appeal_type = models.CharField(max_length=20, choices=[("WithThanks", "WithThanks"), ("VDM", "VDM")], default="WithThanks")
    
    # Tracking Status
    sent = models.BooleanField(default=True)
    opened = models.BooleanField(default=False)
    clicked = models.BooleanField(default=False)
    unsubscribed = models.BooleanField(default=False)
    vdm = models.BooleanField(default=False, help_text="If True, this user is flagged as Do Not Disturb/VDM Blocked")
    failed = models.BooleanField(default=False)
    
    # Video Engagement
    video_played = models.BooleanField(default=False)
    video_started_at = models.DateTimeField(null=True, blank=True)
    video_completed = models.BooleanField(default=False)
    video_completed_at = models.DateTimeField(null=True, blank=True)
    video_watch_duration = models.IntegerField(default=0, help_text="Duration watched in seconds")
    played_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    open_time = models.DateTimeField(null=True, blank=True)
    click_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["campaign", "batch"]),
            models.Index(fields=["job"]),
            models.Index(fields=["appeal_type"]),
        ]

    def __str__(self):
        return f"Track {self.id} - Job {self.job_id} ({'Open' if self.opened else 'Sent'})"
