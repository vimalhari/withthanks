from django.contrib import admin

from .models import (
    Campaign,
    CampaignField,
    Charity,
    CharityMember,
    Donation,
    DonationBatch,
    DonationJob,
    Donor,
    Invoice,
    InvoiceBatch,
    InvoiceLineItem,
    InvoiceService,
    PackageCode,
    ReceivedEmail,
    TextTemplate,
    UnsubscribedUser,
    VideoSendLog,
    VideoTemplate,
)
from .models_analytics import (
    CampaignStats,
    EmailEvent,
    VideoEvent,
    WatchSession,
)


# ---------------------------------------------------------------------------
# Charity & Members
# ---------------------------------------------------------------------------


class CharityMemberInline(admin.TabularInline):
    model = CharityMember
    extra = 0


@admin.register(Charity)
class CharityAdmin(admin.ModelAdmin):
    list_display = ("client_name", "contact_email", "organization_name", "created_at")
    search_fields = ("client_name", "contact_email", "organization_name")
    inlines = [CharityMemberInline]


@admin.register(CharityMember)
class CharityMemberAdmin(admin.ModelAdmin):
    list_display = ("user", "charity", "role", "status", "joined_at")
    list_filter = ("role", "status")
    search_fields = ("user__username", "charity__name")


# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ("total_amount",)


class InvoiceBatchInline(admin.TabularInline):
    model = InvoiceBatch
    extra = 0


@admin.register(InvoiceService)
class InvoiceServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "unit_price", "category", "is_active", "is_tiered")
    list_filter = ("category", "is_active")
    search_fields = ("name",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "charity",
        "amount",
        "status",
        "issue_date",
        "due_date",
        "created_at",
    )
    list_filter = ("status", "invoice_type", "issue_date")
    search_fields = ("invoice_number", "charity__name")
    readonly_fields = ("created_at",)
    ordering = ("-issue_date",)
    inlines = [InvoiceLineItemInline, InvoiceBatchInline]


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    list_display = ("description", "invoice", "quantity", "unit_price", "total_amount")
    search_fields = ("description", "invoice__invoice_number")


@admin.register(InvoiceBatch)
class InvoiceBatchAdmin(admin.ModelAdmin):
    list_display = ("invoice", "batch", "videos_count", "views_count", "line_amount")
    list_filter = ("invoice__status",)
    search_fields = ("invoice__invoice_number", "batch__batch_number")


# ---------------------------------------------------------------------------
# Donation Batches & Jobs (CSV pipeline)
# ---------------------------------------------------------------------------


@admin.register(DonationBatch)
class DonationBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_number", "charity", "campaign_name", "media_type", "created_at")
    list_filter = ("media_type", "created_at")
    search_fields = ("batch_number", "charity__name", "campaign_name")


@admin.register(DonationJob)
class DonationJobAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "amount", "status", "created_at", "completed_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email", "task_id")


# ---------------------------------------------------------------------------
# Unsubscribed Users & Received Emails
# ---------------------------------------------------------------------------


@admin.register(UnsubscribedUser)
class UnsubscribedUserAdmin(admin.ModelAdmin):
    list_display = ("email", "reason", "unsubscribed_from_job", "ip_address", "created_at")
    list_filter = ("created_at",)
    search_fields = ("email", "reason")
    readonly_fields = ("email", "created_at", "ip_address", "user_agent", "unsubscribed_from_job")
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReceivedEmail)
class ReceivedEmailAdmin(admin.ModelAdmin):
    list_display = ("sender", "recipient", "subject", "charity", "received_at")
    list_filter = ("received_at",)
    search_fields = ("sender", "recipient", "subject")
    readonly_fields = ("sender", "recipient", "subject", "body", "received_at", "charity")
    ordering = ("-received_at",)


# ---------------------------------------------------------------------------
# Templates & Package Codes
# ---------------------------------------------------------------------------


@admin.register(TextTemplate)
class TextTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "voice_id", "created_at")
    search_fields = ("name",)


@admin.register(VideoTemplate)
class VideoTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "video_file", "created_at")
    search_fields = ("name",)


@admin.register(PackageCode)
class PackageCodeAdmin(admin.ModelAdmin):
    list_display = ("code",)
    search_fields = ("code",)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class CampaignFieldInline(admin.TabularInline):
    model = CampaignField
    extra = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "client",
        "appeal_type",
        "status",
        "campaign_type",
        "video_mode",
        "appeal_start",
        "appeal_end",
    )
    list_filter = ("status", "appeal_type", "campaign_type", "video_mode")
    search_fields = ("name", "client__name", "appeal_code")
    readonly_fields = ("created_at",)
    inlines = [CampaignFieldInline]


@admin.register(CampaignField)
class CampaignFieldAdmin(admin.ModelAdmin):
    list_display = ("label", "campaign", "field_type", "required", "order")
    list_filter = ("field_type", "required")
    search_fields = ("label", "campaign__name")


# ---------------------------------------------------------------------------
# Stage 3 — Donor / Donation / VideoSendLog (API pipeline)
# ---------------------------------------------------------------------------


@admin.register(Donor)
class DonorAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "charity", "created_at")
    list_filter = ("charity",)
    search_fields = ("email", "full_name", "charity__name")
    readonly_fields = ("created_at",)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ("donor", "charity", "amount", "campaign_type", "source", "donated_at")
    list_filter = ("campaign_type", "source", "donated_at")
    search_fields = ("donor__email", "donor__full_name", "charity__name")
    readonly_fields = ("created_at",)


@admin.register(VideoSendLog)
class VideoSendLogAdmin(admin.ModelAdmin):
    list_display = (
        "recipient_email",
        "charity",
        "donor",
        "send_kind",
        "status",
        "campaign_type",
        "sent_at",
    )
    list_filter = ("status", "send_kind", "campaign_type")
    search_fields = ("recipient_email", "donor__email", "charity__name")
    readonly_fields = ("created_at", "sent_at")


# ---------------------------------------------------------------------------
# Analytics models
# ---------------------------------------------------------------------------


@admin.register(EmailEvent)
class EmailEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "campaign", "job", "timestamp")
    list_filter = ("event_type", "timestamp")
    search_fields = ("campaign__name",)
    readonly_fields = ("id", "timestamp")
    ordering = ("-timestamp",)


@admin.register(VideoEvent)
class VideoEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "campaign", "job", "watch_duration", "completion_percentage", "timestamp")
    list_filter = ("event_type", "timestamp")
    search_fields = ("campaign__name",)
    readonly_fields = ("id", "timestamp")
    ordering = ("-timestamp",)


@admin.register(CampaignStats)
class CampaignStatsAdmin(admin.ModelAdmin):
    list_display = (
        "campaign",
        "total_sent",
        "total_opens",
        "open_rate",
        "total_video_views",
        "completion_rate",
        "last_updated",
    )
    readonly_fields = (
        "total_sent",
        "total_failed",
        "total_opens",
        "unique_opens",
        "total_clicks",
        "total_unsubs",
        "open_rate",
        "click_rate",
        "unsub_rate",
        "bounce_rate",
        "total_video_views",
        "unique_viewers",
        "total_watch_time",
        "avg_watch_duration",
        "completion_rate",
        "rewatch_rate",
        "last_updated",
    )
    search_fields = ("campaign__name",)


@admin.register(WatchSession)
class WatchSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "ip_address", "total_seconds_watched", "created_at")
    search_fields = ("job__name",)
    readonly_fields = ("id", "created_at")
