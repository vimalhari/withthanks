from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from django.contrib import admin, messages
from django.db.models import Count, Q, QuerySet
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline

if TYPE_CHECKING:
    from django.http import HttpRequest

from .analytics_models import (
    CampaignStats,
    EmailEvent,
    VideoEvent,
    WatchSession,
)
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
    ReceivedEmail,
    TextTemplate,
    UnsubscribedUser,
    VideoSendLog,
    VideoTemplate,
)

# ---------------------------------------------------------------------------
# Charity & Members
# ---------------------------------------------------------------------------


class CharityMemberInline(TabularInline):
    model = CharityMember
    extra = 0
    fields = ("user", "role", "status", "joined_at")
    readonly_fields = ("joined_at",)


@admin.action(description="Create a default campaign for selected charities")
def create_default_campaign(
    modeladmin: admin.ModelAdmin,
    request: HttpRequest,
    queryset: QuerySet,
) -> None:
    """
    Replaces the old charity campaign bootstrap flow: creates a default Campaign
    for any selected Charity that doesn't already have one.
    """
    created = 0
    skipped = 0
    for charity in queryset:
        if charity.campaigns.exists():
            skipped += 1
            continue
        year = timezone.now().year
        Campaign.objects.create(
            name=f"Primary Campaign - {charity.charity_name}",
            charity=charity,
            campaign_code=f"PC-{charity.id}-{year}",
            campaign_start=timezone.now().date(),
            campaign_end=timezone.now().date() + datetime.timedelta(days=365),
        )
        created += 1
    if created:
        messages.success(request, f"Created {created} default campaign(s).")
    if skipped:
        messages.info(request, f"Skipped {skipped} charities that already have campaigns.")


@admin.register(Charity)
class CharityAdmin(ModelAdmin):
    list_display = ("charity_name", "contact_email", "created_at")
    search_fields = ("charity_name", "contact_email")
    warn_unsaved_tabs = True
    inlines = [CharityMemberInline]
    actions = [create_default_campaign]
    readonly_fields = (
        "blackbaud_enabled",
        "blackbaud_environment_id",
        "blackbaud_token_expires_at",
        "blackbaud_last_synced_at",
        "blackbaud_crm_status",
    )
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "charity_name",
                    "website_url",
                    "contact_email",
                    "contact_phone",
                    "company_number",
                )
            },
        ),
        (
            "Address",
            {
                "classes": ("collapse",),
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "city",
                    "county",
                    "postcode",
                ),
            },
        ),
        (
            "Billing",
            {
                "classes": ("collapse",),
                "fields": (
                    "billing_email",
                    "additional_emails",
                ),
            },
        ),
        (
            "Blackbaud Raiser's Edge NXT",
            {
                "classes": ("collapse",),
                "fields": (
                    "blackbaud_crm_status",
                    "blackbaud_enabled",
                    "blackbaud_environment_id",
                    "blackbaud_token_expires_at",
                    "blackbaud_last_synced_at",
                ),
            },
        ),
    )

    # ------------------------------------------------------------------
    # Custom admin URLs: connect / disconnect per charity
    # ------------------------------------------------------------------

    def get_urls(self):
        from charity.views_crm import blackbaud_admin_connect, blackbaud_admin_disconnect

        custom = [
            path(
                "<int:charity_id>/connect-blackbaud/",
                self.admin_site.admin_view(blackbaud_admin_connect),
                name="charity_charity_blackbaud_connect",
            ),
            path(
                "<int:charity_id>/disconnect-blackbaud/",
                self.admin_site.admin_view(blackbaud_admin_disconnect),
                name="charity_charity_blackbaud_disconnect",
            ),
        ]
        return custom + super().get_urls()

    # ------------------------------------------------------------------
    # Readonly field: inline Connect / Disconnect button
    # ------------------------------------------------------------------

    @admin.display(description="Raiser's Edge NXT Connection")
    def blackbaud_crm_status(self, obj):
        if not obj or not obj.pk:
            return mark_safe("<em>Save the charity first to connect Raiser's Edge NXT.</em>")

        if obj.blackbaud_enabled:
            last_sync = (
                obj.blackbaud_last_synced_at.strftime("%d %b %Y %H:%M UTC")
                if obj.blackbaud_last_synced_at
                else "never"
            )
            disconnect_url = reverse("admin:charity_charity_blackbaud_disconnect", args=[obj.pk])
            return format_html(
                '<span style="color:#16a34a;font-weight:600;">&#10003; Connected</span> '
                "&mdash; last synced: {last_sync}"
                '<form method="post" action="{url}" style="display:inline;margin-left:16px;">'
                '<input type="hidden" name="csrfmiddlewaretoken" value="">'
                '<button type="submit" '
                'style="background:#dc2626;color:#fff;border:none;padding:4px 12px;'
                'border-radius:4px;cursor:pointer;font-size:12px;" '
                "onclick=\"this.form.querySelector('[name=csrfmiddlewaretoken]').value="
                "document.cookie.match(/csrftoken=([^;]+)/)[1];return confirm('Disconnect Raiser's Edge NXT for this charity?');\">"
                "Disconnect"
                "</button>"
                "</form>",
                last_sync=last_sync,
                url=disconnect_url,
            )

        connect_url = reverse("admin:charity_charity_blackbaud_connect", args=[obj.pk])
        return format_html(
            '<a href="{}" '
            'style="background:#2563eb;color:#fff;padding:5px 14px;'
            'border-radius:4px;text-decoration:none;font-size:12px;font-weight:600;">'
            "&#128279; Connect Raiser's Edge NXT"
            "</a>",
            connect_url,
        )


@admin.register(CharityMember)
class CharityMemberAdmin(ModelAdmin):
    list_display = ("user", "charity", "role", "status", "joined_at")
    list_filter = ("role", "status")
    search_fields = ("user__username", "charity__charity_name")


# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------


class InvoiceLineItemInline(TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ("total_amount",)


class InvoiceBatchInline(TabularInline):
    model = InvoiceBatch
    extra = 0
    readonly_fields = (
        "batch",
        "videos_count",
        "views_count",
        "clicks_count",
        "unsubscribes_count",
        "campaign_name",
        "line_amount",
    )

    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(InvoiceService)
class InvoiceServiceAdmin(ModelAdmin):
    list_display = ("name", "unit_price", "category", "is_active", "is_tiered")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    compressed_fields = True


@admin.register(Invoice)
class InvoiceAdmin(ModelAdmin):
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
    search_fields = ("invoice_number", "charity__charity_name")
    readonly_fields = ("created_at",)
    ordering = ("-issue_date",)
    warn_unsaved_tabs = True
    compressed_fields = True
    inlines = [InvoiceLineItemInline, InvoiceBatchInline]


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(ModelAdmin):
    list_display = ("description", "invoice", "quantity", "unit_price", "total_amount")
    search_fields = ("description", "invoice__invoice_number")
    compressed_fields = True


@admin.register(InvoiceBatch)
class InvoiceBatchAdmin(ModelAdmin):
    list_display = ("invoice", "batch", "videos_count", "views_count", "line_amount")
    list_filter = ("invoice__status",)
    search_fields = ("invoice__invoice_number", "batch__batch_number")
    compressed_fields = True


# ---------------------------------------------------------------------------
# Donation Batches & Jobs (CSV pipeline)
# ---------------------------------------------------------------------------


class DonationJobInline(TabularInline):
    """Read-only inline showing jobs on a batch for quick status overview."""

    model = DonationJob
    extra = 0
    fields = ("donor_name", "email", "donation_amount", "status", "completed_at")
    readonly_fields = ("donor_name", "email", "donation_amount", "status", "completed_at")
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        # Limit to 50 jobs in the inline to keep the page performant
        return super().get_queryset(request).order_by("-created_at")[:50]


@admin.register(DonationBatch)
class DonationBatchAdmin(ModelAdmin):
    list_display = (
        "batch_number",
        "charity",
        "campaign_name",
        "media_type",
        "batch_status",
        "created_at",
    )
    list_filter = ("media_type", "status", "created_at")
    search_fields = ("batch_number", "charity__charity_name", "campaign_name")
    readonly_fields = ("created_at",)
    compressed_fields = True
    inlines = [DonationJobInline]

    @admin.display(description="Status")
    def batch_status(self, obj: DonationBatch) -> str:
        return obj.status


@admin.register(DonationJob)
class DonationJobAdmin(ModelAdmin):
    list_display = (
        "donor_name",
        "email",
        "donation_amount",
        "status",
        "donation_batch",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("donor_name", "email", "task_id")
    compressed_fields = True
    readonly_fields = (
        "task_id",
        "created_at",
        "completed_at",
        "generation_time",
        "real_views",
        "real_clicks",
        "video_path",
        "error_message",
    )


# ---------------------------------------------------------------------------
# Unsubscribed Users & Received Emails (read-only audit trails)
# ---------------------------------------------------------------------------


@admin.register(UnsubscribedUser)
class UnsubscribedUserAdmin(ModelAdmin):
    list_display = ("email", "charity", "reason", "ip_address", "created_at")
    list_filter = ("created_at",)
    search_fields = ("email", "reason")
    readonly_fields = (
        "email",
        "charity",
        "created_at",
        "ip_address",
        "user_agent",
        "unsubscribed_from_job",
    )
    ordering = ("-created_at",)
    compressed_fields = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(ReceivedEmail)
class ReceivedEmailAdmin(ModelAdmin):
    list_display = ("sender", "recipient", "subject", "charity", "received_at")
    list_filter = ("received_at",)
    search_fields = ("sender", "recipient", "subject")
    readonly_fields = ("sender", "recipient", "subject", "body", "received_at", "charity")
    ordering = ("-received_at",)
    compressed_fields = True


# ---------------------------------------------------------------------------
# Templates & Package Codes
# ---------------------------------------------------------------------------


@admin.register(TextTemplate)
class TextTemplateAdmin(ModelAdmin):
    list_display = ("name", "voice_id", "created_at")
    search_fields = ("name",)


@admin.register(VideoTemplate)
class VideoTemplateAdmin(ModelAdmin):
    list_display = ("name", "video_file", "created_at")
    search_fields = ("name",)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class CampaignFieldInline(TabularInline):
    model = CampaignField
    extra = 0
    fields = ("label", "field_type", "required", "order")


class DonationBatchCampaignInline(TabularInline):
    """Read-only inline to show batch summary on a Campaign — replaces campaign_detail view."""

    model = DonationBatch
    extra = 0
    verbose_name = "Donation Batch"
    verbose_name_plural = "Donation Batches"
    fields = (
        "batch_number",
        "media_type",
        "status",
        "success_count",
        "failed_count",
        "pending_count",
        "created_at",
    )
    readonly_fields = (
        "batch_number",
        "media_type",
        "status",
        "success_count",
        "failed_count",
        "pending_count",
        "created_at",
    )
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    @admin.display(description="Success")
    def success_count(self, obj: DonationBatch) -> int:
        return obj.jobs.filter(status="success").count()

    @admin.display(description="Failed")
    def failed_count(self, obj: DonationBatch) -> int:
        return obj.jobs.filter(status="failed").count()

    @admin.display(description="Pending")
    def pending_count(self, obj: DonationBatch) -> int:
        return obj.jobs.filter(Q(status="pending") | Q(status="processing")).count()

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        return (
            super().get_queryset(request).annotate(_job_count=Count("jobs")).order_by("-created_at")
        )


@admin.register(Campaign)
class CampaignAdmin(ModelAdmin):
    list_display = (
        "name",
        "charity",
        "campaign_start",
        "campaign_end",
        "is_paused",
        "campaign_mode",
    )
    list_filter = ("is_paused", "campaign_mode")
    search_fields = ("name", "charity__charity_name", "campaign_code")
    readonly_fields = ("id", "created_at")
    warn_unsaved_tabs = True
    inlines = [CampaignFieldInline, DonationBatchCampaignInline]
    fieldsets = (
        (
            "Campaign Identity",
            {
                "fields": (
                    "id",
                    "name",
                    "charity",
                    "campaign_code",
                    "created_at",
                )
            },
        ),
        (
            "Type & Mode",
            {
                "fields": (
                    "campaign_mode",
                    "gratitude_cooldown_days",  # Thank You campaigns only
                )
            },
        ),
        (
            "Schedule",
            {
                "fields": (
                    "campaign_start",
                    "campaign_end",
                    "is_paused",
                )
            },
        ),
        (
            "Email Settings",
            {
                "classes": ("collapse",),
                "fields": ("from_email", "vdm_email_body", "email_thumbnail"),
            },
        ),
        (
            "Video Assets",
            {
                "classes": ("collapse",),
                "fields": (
                    "cf_stream_video_id",
                    "cf_stream_video_url",
                    "charity_video",
                    "gratitude_video",
                    "base_video",
                    "voiceover_script",
                    "voice_id",
                ),
            },
        ),
        (
            "Post-Video CTA",
            {
                "classes": ("collapse",),
                "description": "Optional call-to-action button shown as an overlay when the video ends on the donor landing page.",
                "fields": (
                    "cta_url",
                    "cta_label",
                ),
            },
        ),
    )


@admin.register(CampaignField)
class CampaignFieldAdmin(ModelAdmin):
    list_display = ("label", "campaign", "field_type", "required", "order")
    list_filter = ("field_type", "required")
    search_fields = ("label", "campaign__name")
    compressed_fields = True


# ---------------------------------------------------------------------------
# Stage 3 — Donor / Donation / VideoSendLog (API pipeline)
# ---------------------------------------------------------------------------


@admin.register(Donor)
class DonorAdmin(ModelAdmin):
    list_display = ("full_name", "email", "charity", "created_at")
    list_filter = ("charity",)
    search_fields = ("email", "full_name", "charity__charity_name")
    readonly_fields = ("created_at",)
    compressed_fields = True


@admin.register(Donation)
class DonationAdmin(ModelAdmin):
    list_display = ("donor", "charity", "amount", "campaign_type", "source", "donated_at")
    list_filter = ("campaign_type", "source", "donated_at")
    search_fields = ("donor__email", "donor__full_name", "charity__charity_name")
    readonly_fields = ("created_at",)
    compressed_fields = True


@admin.register(VideoSendLog)
class VideoSendLogAdmin(ModelAdmin):
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
    search_fields = ("recipient_email", "donor__email", "charity__charity_name")
    readonly_fields = ("created_at", "sent_at")
    compressed_fields = True


# ---------------------------------------------------------------------------
# Analytics models
# ---------------------------------------------------------------------------


@admin.register(EmailEvent)
class EmailEventAdmin(ModelAdmin):
    list_display = ("event_type", "campaign", "job", "timestamp")
    list_filter = ("event_type", "timestamp")
    search_fields = ("campaign__name",)
    readonly_fields = ("id", "timestamp")
    ordering = ("-timestamp",)
    compressed_fields = True


@admin.register(VideoEvent)
class VideoEventAdmin(ModelAdmin):
    list_display = (
        "event_type",
        "campaign",
        "job",
        "watch_duration",
        "completion_percentage",
        "timestamp",
    )
    list_filter = ("event_type", "timestamp")
    search_fields = ("campaign__name",)
    readonly_fields = ("id", "timestamp")
    ordering = ("-timestamp",)
    compressed_fields = True


@admin.register(CampaignStats)
class CampaignStatsAdmin(ModelAdmin):
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
class WatchSessionAdmin(ModelAdmin):
    list_display = ("id", "job", "ip_address", "total_seconds_watched", "created_at")
    search_fields = ("job__donor_name",)
    readonly_fields = ("id", "created_at")
    compressed_fields = True
