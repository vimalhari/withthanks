import uuid

from django.db import models
from django.db.models import Count, Q, Sum
from django.utils import timezone


class EmailEvent(models.Model):
    EVENT_TYPES = [
        ("SENT", "Sent"),
        ("FAILED", "Failed"),
        ("BOUNCED", "Bounced"),
        ("OPEN", "Open"),
        ("CLICK", "Click"),
        ("UNSUB", "Unsubscribe"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.IntegerField(
        null=True, blank=True
    )  # Mapped to DonationJob ID (Backward compatibility)
    campaign = models.ForeignKey(
        "charity.Campaign",
        on_delete=models.CASCADE,
        related_name="email_events",
        null=True,
        blank=True,
    )
    job = models.ForeignKey(
        "charity.DonationJob",
        on_delete=models.CASCADE,
        related_name="email_events",
        null=True,
        blank=True,
    )

    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    timestamp = models.DateTimeField(default=timezone.now)

    # Metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["event_type", "timestamp"]),
            models.Index(fields=["campaign"]),
        ]

    def __str__(self):
        return f"{self.event_type} - Campaign {self.campaign_id}"

    def save(self, *args, **kwargs):
        # STRICT LOGIC: Reject UNSUB for THANKYOU campaigns
        if (
            self.event_type in ["UNSUB", "unsub"]
            and self.campaign
            and self.campaign.appeal_type == "THANKYOU"
        ):
            return  # Silently ignore
        super().save(*args, **kwargs)


class VideoEvent(models.Model):
    EVENT_TYPES = [
        ("GENERATED", "Generated"),
        ("PLAY", "Play"),
        ("PROGRESS", "Progress"),
        ("COMPLETE", "Complete"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        "WatchSession", on_delete=models.CASCADE, related_name="video_events", null=True, blank=True
    )
    campaign = models.ForeignKey(
        "charity.Campaign",
        on_delete=models.CASCADE,
        related_name="video_events",
        null=True,
        blank=True,
    )
    user_id = models.IntegerField(null=True, blank=True)
    job = models.ForeignKey(
        "charity.DonationJob",
        on_delete=models.CASCADE,
        related_name="video_events",
        null=True,
        blank=True,
    )

    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    watch_duration = models.FloatField(default=0.0, help_text="Duration in seconds")
    completion_percentage = models.FloatField(default=0.0)
    timestamp = models.DateTimeField(default=timezone.now)

    # Cloudflare Specific
    cloudflare_video_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["event_type", "timestamp"]),
            models.Index(fields=["campaign"]),
        ]

    def __str__(self):
        return f"{self.event_type} - {self.completion_percentage}%"


class CampaignStats(models.Model):
    campaign = models.OneToOneField(
        "charity.Campaign", on_delete=models.CASCADE, related_name="stats"
    )

    # Email Metrics
    total_sent = models.PositiveIntegerField(default=0)
    total_failed = models.PositiveIntegerField(default=0)
    total_opens = models.PositiveIntegerField(default=0)
    unique_opens = models.PositiveIntegerField(default=0)
    total_clicks = models.PositiveIntegerField(default=0)
    total_unsubs = models.PositiveIntegerField(default=0)

    open_rate = models.FloatField(default=0.0)
    click_rate = models.FloatField(default=0.0)
    unsub_rate = models.FloatField(default=0.0)
    bounce_rate = models.FloatField(default=0.0)

    # Video Metrics
    total_video_views = models.PositiveIntegerField(default=0)
    unique_viewers = models.PositiveIntegerField(default=0)
    total_watch_time = models.FloatField(default=0.0)
    avg_watch_duration = models.FloatField(default=0.0)
    completion_rate = models.FloatField(default=0.0)
    rewatch_rate = models.FloatField(default=0.0)

    last_updated = models.DateTimeField(auto_now=True)

    def update_stats(self):
        """Recalculate stats from events"""
        email_stats = EmailEvent.objects.filter(campaign=self.campaign).aggregate(
            sent=Count("id", filter=Q(event_type="SENT")),
            failed=Count("id", filter=Q(event_type__in=["FAILED", "BOUNCED"])),
            opens=Count("id", filter=Q(event_type="OPEN")),
            unique_opens=Count("job", filter=Q(event_type="OPEN"), distinct=True),
            clicks=Count("id", filter=Q(event_type="CLICK")),
            unsubs=Count("id", filter=Q(event_type="UNSUB")),
        )

        video_stats = VideoEvent.objects.filter(campaign=self.campaign).aggregate(
            views=Count("id", filter=Q(event_type="PLAY")),
            unique_viewers=Count("job", distinct=True),
            total_duration=Sum("watch_duration"),
            completions=Count("id", filter=Q(event_type="COMPLETE")),
        )

        # Apply Counts
        self.total_sent = email_stats["sent"] or 0
        self.total_failed = email_stats["failed"] or 0
        self.total_opens = email_stats["opens"] or 0
        self.unique_opens = email_stats["unique_opens"] or 0
        self.total_clicks = email_stats["clicks"] or 0
        self.total_unsubs = email_stats["unsubs"] or 0

        self.total_video_views = video_stats["views"] or 0
        self.unique_viewers = video_stats["unique_viewers"] or 0
        self.total_watch_time = video_stats["total_duration"] or 0.0

        # Calculate Rates
        if self.total_sent > 0:
            self.open_rate = round((self.unique_opens / self.total_sent) * 100, 2)
            self.click_rate = round((self.total_clicks / self.total_sent) * 100, 2)
            self.unsub_rate = round((self.total_unsubs / self.total_sent) * 100, 2)
            self.bounce_rate = round((self.total_failed / self.total_sent) * 100, 2)

        if self.total_video_views > 0:
            self.avg_watch_duration = round(self.total_watch_time / self.total_video_views, 2)
            self.completion_rate = round(
                (video_stats["completions"] or 0) / self.total_video_views * 100, 2
            )

        if self.unique_viewers > 0:
            self.rewatch_rate = round(
                ((self.total_video_views - self.unique_viewers) / self.unique_viewers) * 100, 2
            )

        self.save()
        return True


class WatchSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        "charity.DonationJob", on_delete=models.CASCADE, related_name="watch_sessions"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    total_seconds_watched = models.IntegerField(default=0)

    def __str__(self):
        return f"Session {self.id} for Job {self.job_id}"
