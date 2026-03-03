import uuid

from django.contrib.auth.models import User
from django.db import models

from charity.utils.media_utils import get_client_media_path


# Create your models here.
class Charity(models.Model):
    # CLIENT MODEL (MINIMAL & FINAL)
    client_name = models.CharField(max_length=255)
    contact_email = models.EmailField()
    organization_name = models.CharField(max_length=255)
    default_template_video = models.FileField(
        upload_to=get_client_media_path, blank=True, null=True, help_text="fallback MP4"
    )
    gratitude_card = models.FileField(
        upload_to=get_client_media_path,
        blank=True,
        null=True,
        help_text="Gratitude card (Video or Image)",
    )

    # Billing Information
    billing_email = models.EmailField(
        blank=True, null=True, help_text="Override contact email for invoices"
    )
    billing_address = models.TextField(
        blank=True, null=True, help_text="Specific billing address for invoices"
    )

    # Blackbaud Integration
    blackbaud_client_id = models.CharField(
        max_length=255, blank=True, null=True, help_text="Blackbaud SKY API Client ID"
    )
    blackbaud_client_secret = models.CharField(
        max_length=255, blank=True, null=True, help_text="Blackbaud SKY API Client Secret"
    )
    blackbaud_enabled = models.BooleanField(
        default=False, help_text="Enable Raiser's Edge integration"
    )

    # Defaults used by processing pipeline
    default_voiceover_script = models.TextField(
        blank=True,
        help_text="Default script with placeholders {{donor_name}}, {{donation_amount}}, {{organization_name}}",
    )
    default_voice_id = models.CharField(
        max_length=128, blank=True, help_text="Default ElevenLabs voice ID"
    )

    # User Access
    members = models.ManyToManyField(
        User, through="CharityMember", related_name="charity_memberships", blank=True
    )

    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    company_number = models.CharField(max_length=50, blank=True, null=True)

    # Physical Address
    address_line_1 = models.CharField(max_length=255, blank=True, null=True)
    address_line_2 = models.CharField(max_length=255, blank=True, null=True)
    county = models.CharField(max_length=100, blank=True, null=True)
    postcode = models.CharField(max_length=20, blank=True, null=True)

    # Additional billing contacts (comma-separated; inherited by new invoices)
    additional_emails = models.TextField(
        blank=True,
        null=True,
        help_text="Comma-separated default CC email addresses for invoice delivery",
    )

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
        ("Admin", "Admin"),
        ("Member", "Member"),
        ("Viewer", "Viewer"),
    ]
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("INACTIVE", "Inactive"),
        ("PENDING", "Pending"),
    ]

    charity = models.ForeignKey(Charity, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="Member")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("charity", "user")

    def __str__(self):
        return f"{self.user.username} - {self.charity.name} ({self.role})"


class InvoiceService(models.Model):
    """Catalog of billable services"""

    CATEGORY_CHOICES = [
        ("setup", "Set Up & Management"),
        ("production", "Video Production"),
        ("gratitude", "Gratitude Cards"),
        ("postage", "Postage & Printing"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    is_active = models.BooleanField(default=True)

    # Tiered pricing support (optional for now, can be JSON or simple fields)
    is_tiered = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (${self.unit_price})"


class Invoice(models.Model):
    STATUS_CHOICES = [
        ("Draft", "Draft"),
        ("Sent", "Sent"),
        ("Paid", "Paid"),
        ("Overdue", "Overdue"),
        ("Void", "Void"),
    ]

    INVOICE_TYPE_CHOICES = [
        ("campaign_wise", "Campaign Wise"),
        ("single_batch", "Single Batch"),
        ("multiple_batches", "Multiple Batches"),
        ("date_range", "Date Range"),
    ]

    PRICING_TIER_CHOICES = [
        ("standard", "Standard"),
        ("premium", "Premium"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="invoices")
    campaign = models.ForeignKey(
        "Campaign", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )
    invoice_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")
    issue_date = models.DateField()
    due_date = models.DateField()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # NEW FIELDS for batch-based billing
    invoice_type = models.CharField(
        max_length=20, choices=INVOICE_TYPE_CHOICES, default="single_batch"
    )

    # Pricing fields
    pricing_tier = models.CharField(max_length=20, choices=PRICING_TIER_CHOICES, default="standard")
    campaign_volume = models.PositiveIntegerField(default=0)
    price_per_video = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    price_per_batch = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    flat_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=20.00
    )  # Default to 20% as per UI screenshot

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

    # Additional recipients (comma-separated; pre-filled from charity.additional_emails)
    additional_billing_emails = models.TextField(
        blank=True,
        null=True,
        help_text="Comma-separated CC email addresses for this invoice",
    )

    # Additional metadata
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-issue_date"]

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.charity.name}"

    def calculate_totals(self):
        """Recalculate line-item totals and persist. Delegates to invoice_service."""
        from charity.services.invoice_service import calculate_invoice_totals

        calculate_invoice_totals(self)
        return self.amount

    def generate_invoice_number(self):
        """Auto-generate invoice number: INV-YYYY-NNNN. Delegates to invoice_service."""
        from charity.services.invoice_service import generate_invoice_number

        self.invoice_number = generate_invoice_number()
        return self.invoice_number


class InvoiceLineItem(models.Model):
    """Individual line items on an invoice"""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")
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

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="invoice_batches")
    batch = models.ForeignKey("DonationBatch", on_delete=models.PROTECT, related_name="invoices")

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
        unique_together = ("invoice", "batch")
        ordering = ["batch__created_at"]

    def __str__(self):
        return f"Invoice {self.invoice.invoice_number} - Batch #{self.batch.batch_number}"


class DonationBatch(models.Model):
    class BatchStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors", "Completed with Errors"
        FAILED = "failed", "Failed"

    charity = models.ForeignKey(
        Charity, on_delete=models.CASCADE, related_name="batches", null=True, blank=True
    )
    campaign = models.ForeignKey(
        "Campaign", on_delete=models.SET_NULL, null=True, blank=True, related_name="batches"
    )
    media_type = models.CharField(
        max_length=20, choices=[("video", "Video"), ("image", "Image")], default="video"
    )
    campaign_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    csv_filename = models.CharField(max_length=255, blank=True)
    batch_number = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=25,
        choices=BatchStatus.choices,
        default=BatchStatus.PENDING,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Batch #{self.batch_number} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    @classmethod
    def get_next_batch_number(cls, charity):
        last = cls.objects.filter(charity=charity).order_by("id").last()
        if not last:
            # Fallback to order by batch_number if id ordering isn't certain
            last = cls.objects.filter(charity=charity).order_by("batch_number").last()
        return last.batch_number + 1 if last else 1

    @property
    def total_records(self):
        return self.jobs.count()

    @property
    def success_count(self):
        return self.jobs.filter(status="success").count()

    @property
    def failed_count(self):
        return self.jobs.filter(status="failed").count()

    @property
    def pending_count(self):
        return self.jobs.filter(status__in=["pending", "processing"]).count()

    @property
    def upload_type(self):
        if self.csv_filename and "manual_entry.csv" not in self.csv_filename:
            return "CSV"
        return "Manual"


class DonationJob(models.Model):
    # CORE FIELDS
    donor_name = models.CharField(max_length=255)
    email = models.EmailField()
    donation_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # REFERENCES
    charity = models.ForeignKey(
        Charity, on_delete=models.CASCADE, related_name="jobs", null=True, blank=True
    )
    campaign = models.ForeignKey(
        "Campaign", on_delete=models.SET_NULL, null=True, blank=True, related_name="campaign_jobs"
    )
    donation_batch = models.ForeignKey(
        DonationBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs"
    )

    # STATUS & TRACKING
    status = models.CharField(
        max_length=20, default="pending"
    )  # pending, processing, success, failed
    video_path = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    task_id = models.CharField(max_length=128, blank=True, null=True)
    appeal_type = models.CharField(
        max_length=20, choices=[("WithThanks", "WithThanks"), ("VDM", "VDM")], null=True, blank=True
    )
    media_type_override = models.CharField(
        max_length=20, choices=[("video", "Video"), ("image", "Image")], null=True, blank=True
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generation_time = models.FloatField(null=True, blank=True)

    # Stats
    real_views = models.PositiveIntegerField(default=0)
    real_clicks = models.PositiveIntegerField(default=0)

    # Resend message ID — populated after email dispatch; used to link webhook events back
    resend_message_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="ID returned by Resend API after email dispatch; used to correlate webhook events",
    )

    @property
    def total_views(self):
        return self.real_views

    @property
    def video_url(self):
        """Return the cloud URL for this job's video (R2 or Cloudflare Stream)."""
        if not self.video_path:
            return None
        path_str = str(self.video_path)
        # video_path is always a full cloud URL (R2 or Stream) — return it directly.
        if path_str.startswith(("http://", "https://")):
            return path_str
        # Legacy: relative R2 key — construct URL via storage backend.
        from django.core.files.storage import default_storage

        try:
            return default_storage.url(path_str)
        except Exception:
            return None

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["email"]),
            models.Index(fields=["created_at"]),
            # Compound index covering the 30-day deduplication query in Stage 1
            models.Index(
                fields=["charity", "email", "status", "completed_at"],
                name="donationjob_dedup_idx",
            ),
        ]

    def get_status_badge_class(self):
        """Return Bootstrap badge class based on status"""
        return {
            "pending": "warning",
            "success": "success",
            "failed": "danger",
            "skipped": "secondary",
        }.get(self.status, "secondary")

    def __str__(self):
        return f"Job {self.id} - {self.donor_name} ({self.status})"


class UnsubscribedUser(models.Model):
    charity = models.ForeignKey(
        Charity, on_delete=models.CASCADE, related_name="unsubscribes", null=True, blank=True
    )
    email = models.EmailField()  # Remove unique=True here
    reason = models.TextField(blank=True)
    unsubscribed_from_job = models.ForeignKey(
        DonationJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unsubscribes_triggered",
        help_text="The donation job that triggered this unsubscribe",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, help_text="Browser user agent string")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("charity", "email")
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
    charity = models.ForeignKey(
        Charity, on_delete=models.CASCADE, related_name="received_emails", null=True, blank=True
    )
    sender = models.EmailField()
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"To {self.charity.name if self.charity else 'Unknown'}: {self.subject}"


# Import Analytics Models for discovery (moved to bottom to avoid circular imports during forms initialization)


# ---------------------------------------------------------------------------
# Stage 3 — Template models (used by API pipeline / video_dispatch service)
# ---------------------------------------------------------------------------


class TextTemplate(models.Model):
    """Voiceover script template with an optional ElevenLabs voice ID."""

    name = models.CharField(max_length=255)
    body = models.TextField(
        blank=True,
        help_text="Script with {{donor_name}}, {{donation_amount}}, {{charity}}, {{campaign_name}} placeholders",
    )
    voice_id = models.CharField(max_length=128, blank=True, help_text="ElevenLabs voice ID")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class VideoTemplate(models.Model):
    """Reusable base video asset attached to campaigns."""

    name = models.CharField(max_length=255)
    video_file = models.FileField(upload_to="video_templates/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Campaign(models.Model):
    # Legacy plain-list choices (used by CSV batch pipeline)
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("closed", "Closed"),
    ]
    APPEAL_TYPES = [
        ("WithThanks", "Thank you"),
        ("VDM", "Video Direct Mail (VDM)"),
    ]

    # Stage 3 enums (used by API pipeline / video_dispatch service)
    class CampaignType(models.TextChoices):
        THANK_YOU = "THANK_YOU", "Thank You"
        VDM = "VDM", "Video Direct Mail"

    class VideoMode(models.TextChoices):
        PERSONALIZED = "PERSONALIZED", "Personalized (TTS + stitch)"
        TEMPLATE = "TEMPLATE", "Template-only (pre-rendered)"

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

    # Stage 3 fields (API pipeline)
    campaign_type = models.CharField(
        max_length=20,
        choices=CampaignType.choices,
        default=CampaignType.THANK_YOU,
        help_text="API pipeline campaign type",
    )
    video_mode = models.CharField(
        max_length=20,
        choices=VideoMode.choices,
        default=VideoMode.PERSONALIZED,
        help_text="How the video is produced for the API pipeline",
    )
    text_template = models.ForeignKey(
        TextTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
        help_text="Voiceover script template (API pipeline)",
    )
    video_template = models.ForeignKey(
        VideoTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns",
        help_text="Base video template (API pipeline)",
    )
    gratitude_video_template = models.ForeignKey(
        VideoTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gratitude_campaigns",
        help_text="Gratitude video template (API pipeline)",
    )
    gratitude_cooldown_days = models.PositiveIntegerField(
        default=30,
        help_text="Days within which a repeat donation triggers a gratitude video instead",
    )

    # NEW CAMPAIGN MEDIA ASSETS
    charity_video = models.FileField(
        upload_to=get_client_media_path,
        blank=True,
        null=True,
        help_text="Main Campaign Video (VDM Appeal)",
    )
    gratitude_video = models.FileField(
        upload_to=get_client_media_path,
        blank=True,
        null=True,
        help_text="Gratitude Video (WithThanks Appeal)",
    )

    video_template_override = models.FileField(
        upload_to=get_client_media_path,
        blank=True,
        null=True,
        help_text="Override the default template video",
    )
    voiceover_script_override = models.TextField(
        blank=True, help_text="Override the default charity voiceover script"
    )

    # Personalization Settings
    is_personalized = models.BooleanField(
        default=False, help_text="Use TTS and personalized stitching (WithThanks only)"
    )

    # Email Settings
    from_email = models.EmailField(
        blank=True, null=True, help_text="Override sender email address for this campaign"
    )

    # Cloudflare Stream cache — populated on first VDM send, reused for all subsequent jobs
    cf_stream_video_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Cloudflare Stream video UID (cached after first VDM upload)",
    )
    cf_stream_video_url = models.URLField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Cloudflare Stream hosted player URL (cached after first VDM upload)",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    # Compatibility properties — video_dispatch.py uses `charity` while the
    # CSV pipeline uses `client`.  Both refer to the same FK.
    @property
    def charity(self):
        return self.client

    @property
    def is_active(self):
        return self.status == "active"


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


# ---------------------------------------------------------------------------
# Stage 3 — Donor / Donation / VideoSendLog (used by API pipeline)
# ---------------------------------------------------------------------------


class Donor(models.Model):
    """
    A unique donor record per charity, keyed by email.

    Created automatically when donations arrive via the API pipeline.
    """

    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="donors")
    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("charity", "email")]
        indexes = [
            models.Index(fields=["charity", "email"]),
        ]

    def __str__(self):
        return f"{self.full_name or self.email} ({self.charity})"


class Donation(models.Model):
    """Individual donation record linked to a Donor."""

    donor = models.ForeignKey(Donor, on_delete=models.CASCADE, related_name="donations")
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="donations")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    donated_at = models.DateTimeField()
    campaign_type = models.CharField(
        max_length=20,
        choices=Campaign.CampaignType.choices,
        default=Campaign.CampaignType.THANK_YOU,
    )
    source = models.CharField(max_length=50, default="API")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Donation #{self.pk} — {self.amount} from {self.donor}"


class VideoSendLog(models.Model):
    """
    Tracks each video email dispatched through the API pipeline.

    Analogous to DonationJob in the CSV batch pipeline, but normalised
    around Donor/Donation instead of raw CSV rows.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    class SendKind(models.TextChoices):
        PERSONALIZED = "PERSONALIZED", "Personalized"
        TEMPLATE = "TEMPLATE", "Template"
        GRATITUDE = "GRATITUDE", "Gratitude"

    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="video_send_logs")
    donor = models.ForeignKey(Donor, on_delete=models.CASCADE, related_name="video_send_logs")
    donation = models.ForeignKey(Donation, on_delete=models.CASCADE, related_name="video_send_logs")
    campaign = models.ForeignKey(
        Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="video_send_logs"
    )

    campaign_type = models.CharField(
        max_length=20,
        choices=Campaign.CampaignType.choices,
        default=Campaign.CampaignType.THANK_YOU,
    )
    send_kind = models.CharField(max_length=20, choices=SendKind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    recipient_email = models.EmailField()
    video_file = models.CharField(max_length=512, blank=True)
    stream_video_id = models.CharField(max_length=255, blank=True)
    stream_playback_url = models.URLField(max_length=512, blank=True)
    stream_thumbnail_url = models.URLField(max_length=512, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)

    sent_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["charity", "donor"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"VideoSendLog #{self.pk} — {self.recipient_email} [{self.status}]"


class EmailTracking(models.Model):
    """
    Tracks the lifecycle of an individual email sent to a donor.
    """

    # Relationships
    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="email_tracks", null=True, blank=True
    )
    batch = models.ForeignKey(
        DonationBatch, on_delete=models.CASCADE, related_name="email_tracks", null=True, blank=True
    )
    job = models.ForeignKey(
        DonationJob, on_delete=models.CASCADE, related_name="email_tracks", null=True, blank=True
    )

    # Metadata
    user_id = models.IntegerField(
        help_text="Mapped to DonationJob ID for backwards compatibility URL params",
        null=True,
        blank=True,
    )
    appeal_type = models.CharField(
        max_length=20, choices=[("WithThanks", "WithThanks"), ("VDM", "VDM")], default="WithThanks"
    )

    # Tracking Status
    sent = models.BooleanField(default=True)
    opened = models.BooleanField(default=False)
    clicked = models.BooleanField(default=False)
    unsubscribed = models.BooleanField(default=False)
    vdm = models.BooleanField(
        default=False, help_text="If True, this user is flagged as Do Not Disturb/VDM Blocked"
    )
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
