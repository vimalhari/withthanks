import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


# Create your models here.
class Charity(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="charity", null=True, blank=True
    )
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class VideoTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="video_templates")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    video_file = models.FileField(upload_to="video_templates/")
    overlay_spec_json = models.JSONField(default=dict, blank=True)
    duration_s = models.PositiveIntegerField(
        default=0, help_text="Optional: video length in seconds"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} . {self.charity.name}"


class TextTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="text_templates")
    name = models.CharField(max_length=255)
    body = models.TextField(
        help_text="Use placeholders like {{donor_name}}, {{donation_amount}}, {{charity}}, {{campaign_name}}"
    )
    locale = models.CharField(max_length=16, default="en")
    voice_id = models.CharField(max_length=128, help_text="ElevenLabs voice id (store for later)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.charity.name} · {self.name} ({self.locale})"


class Donor(models.Model):
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="donors")
    email = models.EmailField()
    full_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("charity", "email")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.charity.name} · {self.email}"


class Campaign(models.Model):
    class CampaignType(models.TextChoices):
        THANK_YOU = "THANK_YOU", "Thank You Video"
        DIRECT_EMAIL = "DIRECT_EMAIL", "Direct Email Video"

    class VideoMode(models.TextChoices):
        TEMPLATE = "TEMPLATE", "Template Video"
        PERSONALIZED = "PERSONALIZED", "Personalized Video"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="campaigns")
    name = models.CharField(max_length=255)
    campaign_type = models.CharField(max_length=32, choices=CampaignType.choices)
    video_mode = models.CharField(max_length=32, choices=VideoMode.choices)
    text_template = models.ForeignKey(
        TextTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="campaigns",
    )
    video_template = models.ForeignKey(
        VideoTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="campaigns",
    )
    gratitude_video_template = models.ForeignKey(
        VideoTemplate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="gratitude_campaigns",
    )
    gratitude_cooldown_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.charity.name} · {self.name}"


class Donation(models.Model):
    donor = models.ForeignKey(Donor, on_delete=models.CASCADE, related_name="donations")
    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="donations")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    campaign_type = models.CharField(
        max_length=32,
        choices=Campaign.CampaignType.choices,
        default=Campaign.CampaignType.THANK_YOU,
    )
    donated_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=16, default="CSV")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-donated_at", "-created_at"]

    def __str__(self):
        return f"{self.donor.email} · {self.amount} · {self.donated_at.date()}"


class VideoSendLog(models.Model):
    class SendKind(models.TextChoices):
        TEMPLATE = "TEMPLATE", "Template"
        PERSONALIZED = "PERSONALIZED", "Personalized"
        GRATITUDE = "GRATITUDE", "Gratitude"

    class Status(models.TextChoices):
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    charity = models.ForeignKey(Charity, on_delete=models.CASCADE, related_name="video_sends")
    donor = models.ForeignKey(Donor, on_delete=models.CASCADE, related_name="video_sends")
    donation = models.ForeignKey(
        Donation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="video_sends",
    )
    campaign = models.ForeignKey(
        Campaign,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="video_sends",
    )
    campaign_type = models.CharField(max_length=32, choices=Campaign.CampaignType.choices)
    send_kind = models.CharField(max_length=32, choices=SendKind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SENT)
    sent_at = models.DateTimeField(default=timezone.now)
    recipient_email = models.EmailField()
    video_file = models.FilePathField(max_length=1024)
    # Cloudflare Stream fields – populated after a successful Stream upload.
    stream_video_id = models.CharField(max_length=64, blank=True, db_index=True)
    stream_playback_url = models.URLField(max_length=512, blank=True)
    stream_thumbnail_url = models.URLField(max_length=512, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at", "-created_at"]

    def __str__(self):
        return f"{self.recipient_email} · {self.send_kind} · {self.status}"
