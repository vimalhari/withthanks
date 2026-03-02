from django.contrib import admin
from django.utils.html import format_html

from .models import Campaign, Charity, Donation, Donor, TextTemplate, VideoSendLog, VideoTemplate


@admin.register(Charity)
class CharityAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "user", "created_at")
    search_fields = ("name", "user__email", "user__username")
    list_filter = ("created_at",)
    ordering = ("name",)


@admin.register(VideoTemplate)
class VideoTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "charity", "duration_s", "is_active", "created_at")
    list_filter = ("charity", "is_active")
    search_fields = ("name", "charity__name")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at")


@admin.register(TextTemplate)
class TextTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "charity", "locale", "voice_id", "is_active")
    list_filter = ("charity", "locale", "is_active")
    search_fields = ("name", "charity__name", "body")
    ordering = ("name",)
    readonly_fields = ("id",)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "charity",
        "campaign_type",
        "video_mode",
        "gratitude_cooldown_days",
        "is_active",
        "created_at",
    )
    list_filter = ("charity", "campaign_type", "video_mode", "is_active")
    search_fields = ("name", "charity__name")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at")
    autocomplete_fields = ("text_template", "video_template", "gratitude_video_template")


@admin.register(Donor)
class DonorAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "charity", "created_at")
    list_filter = ("charity",)
    search_fields = ("email", "full_name", "charity__name")
    ordering = ("-created_at",)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("donor", "charity", "amount", "campaign_type", "source", "donated_at")
    list_filter = ("charity", "campaign_type", "source")
    search_fields = ("donor__email", "donor__full_name", "charity__name")
    ordering = ("-donated_at",)
    date_hierarchy = "donated_at"


@admin.register(VideoSendLog)
class VideoSendLogAdmin(admin.ModelAdmin):
    list_display = (
        "recipient_email",
        "charity",
        "campaign_type",
        "send_kind",
        "status",
        "stream_link",
        "sent_at",
    )
    list_filter = ("charity", "campaign_type", "send_kind", "status")
    search_fields = ("recipient_email", "charity__name", "stream_video_id", "provider_message_id")
    ordering = ("-sent_at",)
    readonly_fields = (
        "charity",
        "donor",
        "donation",
        "campaign",
        "sent_at",
        "created_at",
        "stream_video_id",
        "stream_playback_url",
        "stream_thumbnail_url",
        "provider_message_id",
    )

    @admin.display(description="Stream")
    def stream_link(self, obj: VideoSendLog):
        if obj.stream_playback_url:
            return format_html('<a href="{}" target="_blank">▶ Watch</a>', obj.stream_playback_url)
        return "—"

