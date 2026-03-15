from __future__ import annotations

import contextlib
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db.models import Count, Q, QuerySet
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
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
from .forms import AdminCampaignCSVUploadForm
from .models import (
    Campaign,
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
    UnsubscribedUser,
    VideoSendLog,
)
from .services.video_pipeline_service import resolve_storage_video_url
from .utils.batch_uploads import create_and_enqueue_csv_batch

# ---------------------------------------------------------------------------
# Charity & Members
# ---------------------------------------------------------------------------

ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_LOGO_FILE_SIZE = 2 * 1024 * 1024


def _resolve_admin_file_preview_url(file_value) -> str:
    if not file_value or not getattr(file_value, "name", ""):
        return ""

    resolved_url = resolve_storage_video_url(
        storage_path=file_value.name,
        server_url=settings.SERVER_BASE_URL,
    )
    if resolved_url:
        return resolved_url

    try:
        fallback_url = file_value.url
    except ValueError:
        return ""

    if ".r2.cloudflarestorage.com" in fallback_url:
        return ""
    return fallback_url


def _delete_storage_asset(storage_path: str) -> None:
    if not storage_path:
        return

    with contextlib.suppress(Exception):
        default_storage.delete(storage_path)


class CharityAdminForm(forms.ModelForm):
    class Meta:
        model = Charity
        fields = "__all__"

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if not logo:
            return logo

        extension = Path(logo.name).suffix.lower()
        if extension not in ALLOWED_LOGO_EXTENSIONS:
            raise forms.ValidationError(
                "Upload a PNG, JPG, JPEG, GIF, or WEBP image for the charity logo."
            )

        if logo.size > MAX_LOGO_FILE_SIZE:
            raise forms.ValidationError("Logo files must be 2 MB or smaller.")

        return logo


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


@admin.action(
    description="Re-subscribe selected donors",
    permissions=["change"],
)
def resubscribe_selected_donors(
    modeladmin: admin.ModelAdmin,
    request: HttpRequest,
    queryset: QuerySet,
) -> None:
    """Remove selected charity-scoped unsubscribe records after admin confirmation."""
    if not request.user.is_superuser:
        raise PermissionDenied("Only superusers can re-subscribe donors.")

    selected_ids = list(queryset.values_list("id", flat=True))
    if not selected_ids:
        messages.info(request, "No unsubscribe records were selected.")
        return

    deleted_count, _ = UnsubscribedUser.objects.filter(id__in=selected_ids).delete()
    messages.success(
        request,
        (
            f"Re-subscribed {deleted_count} donor(s). Future VDM sends are allowed again "
            "for those charity/email pairs."
        ),
    )


@admin.register(Charity)
class CharityAdmin(ModelAdmin):
    form = CharityAdminForm
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
        "logo_preview",
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
            "Branding",
            {
                "fields": (
                    "logo",
                    "logo_preview",
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

    @admin.display(description="Logo preview")
    def logo_preview(self, obj):
        if not obj or not obj.logo:
            return "No logo uploaded."

        preview_url = _resolve_admin_file_preview_url(obj.logo)
        if not preview_url:
            return "Logo uploaded, but no public preview URL is available."

        return format_html(
            '<a href="{url}" target="_blank" rel="noopener">'
            '<img src="{url}" alt="{name} logo" '
            'style="display:block;max-width:220px;max-height:100px;object-fit:contain;'
            'border:1px solid #d5d7da;border-radius:6px;background:#fff;padding:8px;">'
            "</a>",
            url=preview_url,
            name=obj.charity_name,
        )

    def save_model(self, request, obj, form, change):
        previous_logo_name = ""
        if change and obj.pk:
            previous_logo_name = (
                Charity.objects.filter(pk=obj.pk).values_list("logo", flat=True).first()
            )

        super().save_model(request, obj, form, change)

        current_logo_name = obj.logo.name if obj.logo else ""
        if previous_logo_name and previous_logo_name != current_logo_name:
            _delete_storage_asset(previous_logo_name)


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
    fields = ("donor_display_name", "email", "donation_amount", "status", "completed_at")
    readonly_fields = (
        "donor_display_name",
        "email",
        "donation_amount",
        "status",
        "completed_at",
    )
    show_change_link = True

    @admin.display(description="Donor")
    def donor_display_name(self, obj: DonationJob) -> str:
        return obj.display_donor_name

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
        "donor_display_name",
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

    @admin.display(description="Donor")
    def donor_display_name(self, obj: DonationJob) -> str:
        return obj.display_donor_name


# ---------------------------------------------------------------------------
# Unsubscribed Users & Received Emails (read-only audit trails)
# ---------------------------------------------------------------------------


@admin.register(UnsubscribedUser)
class UnsubscribedUserAdmin(ModelAdmin):
    list_display = ("email", "charity", "reason", "ip_address", "created_at")
    list_filter = ("created_at",)
    search_fields = ("email", "reason")
    actions = [resubscribe_selected_donors]
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
# Campaigns
# ---------------------------------------------------------------------------


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


class CampaignAdminForm(forms.ModelForm):
    _DEFAULT_MODE_HELP_TEXT = (
        "No mode selected yet. Choose a mode, then save to load the matching fields below."
    )
    _MODE_HELP_TEXTS = {
        Campaign.CampaignMode.THANK_YOU_PERSONALIZED: (
            "PERSONALIZED: each donor gets a generated TTS voiceover stitched onto the "
            "base video. After save, you should see Base Video, Voiceover Script, and "
            "Voice ID fields."
        ),
        Campaign.CampaignMode.THANK_YOU_STANDARD: (
            "STANDARD: one pre-rendered Thank You video is sent directly to donors, while "
            "the email stays personalized. After save, you should see Base Video and "
            "Gratitude Video fields."
        ),
        Campaign.CampaignMode.VDM: (
            "VDM: one shared campaign video is sent to every donor in the batch. After "
            "save, you should see VDM Video and Cloudflare Stream cache fields."
        ),
    }

    class Meta:
        model = Campaign
        fields = "__all__"

    @staticmethod
    def _help_text_attr_name(mode: str) -> str:
        return f"data-help-text-{mode.lower().replace('_', '-')}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email_thumbnail"].widget = AdminPublicMediaFileWidget()
        campaign_mode_field = self.fields["campaign_mode"]
        campaign_mode_field.widget.attrs["data-default-help-text"] = self._DEFAULT_MODE_HELP_TEXT
        for mode, help_text in self._MODE_HELP_TEXTS.items():
            campaign_mode_field.widget.attrs[self._help_text_attr_name(mode)] = help_text
        selected_mode = self.instance.campaign_mode if self.instance and self.instance.pk else None
        if not selected_mode:
            selected_mode = self.initial.get("campaign_mode") or self.data.get("campaign_mode")
        campaign_mode_field.help_text = self._MODE_HELP_TEXTS.get(
            selected_mode,
            self._DEFAULT_MODE_HELP_TEXT,
        )


@dataclass(frozen=True)
class _AdminResolvedFileValue:
    name: str
    url: str

    def __str__(self) -> str:
        return self.name


class AdminPublicMediaFileWidget(forms.ClearableFileInput):
    template_name = "admin/widgets/public_media_file_input.html"
    _IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

    def get_context(self, name, value, attrs):
        display_name = getattr(value, "name", "") if value else ""
        resolved_url = ""

        if value and getattr(value, "name", ""):
            resolved_url = resolve_storage_video_url(
                storage_path=value.name,
                server_url=settings.SERVER_BASE_URL,
            )
            if resolved_url:
                value = _AdminResolvedFileValue(name=value.name, url=resolved_url)

        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        widget["display_name"] = display_name
        widget["public_url"] = resolved_url
        widget["is_image_preview"] = display_name.lower().endswith(self._IMAGE_SUFFIXES)
        widget["missing_file"] = bool(display_name and not resolved_url)
        return context


@admin.register(Campaign)
class CampaignAdmin(ModelAdmin):
    form = CampaignAdminForm

    class Media:
        js = ("charity/campaign_admin.js",)

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
    readonly_fields = (
        "id",
        "created_at",
        "cf_stream_video_id",
        "cf_stream_video_url",
        "upload_csv_action",
    )
    warn_unsaved_tabs = True
    inlines = [DonationBatchCampaignInline]

    # Base fieldsets always displayed regardless of mode
    _BASE_FIELDSETS = [
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
                "fields": ("campaign_mode",),
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
    ]

    _CTA_FIELDSET = (
        "Post-Video CTA",
        {
            "classes": ("collapse",),
            "description": (
                "Optional call-to-action overlay shown when the video ends on the donor "
                "landing page. You can customize the button, headline, and supporting copy."
            ),
            "fields": ("cta_url", "cta_label", "cta_title", "cta_message"),
        },
    )

    def get_urls(self):
        custom = [
            path(
                "<path:object_id>/upload-csv/",
                self.admin_site.admin_view(self.upload_csv_view),
                name="charity_campaign_upload_csv",
            ),
        ]
        return custom + super().get_urls()

    def upload_csv_view(self, request: HttpRequest, object_id: str):
        campaign = self.get_object(request, object_id)
        if campaign is None:
            raise Http404("Campaign not found.")
        if not self.has_change_permission(request, campaign):
            raise PermissionDenied

        if request.method == "POST":
            form = AdminCampaignCSVUploadForm(request.POST, request.FILES)
            if form.is_valid():
                csv_file = form.cleaned_data["csv_file"]
                batch = create_and_enqueue_csv_batch(
                    charity=campaign.charity,
                    csv_file=csv_file,
                    campaign=campaign,
                )
                messages.success(
                    request,
                    (
                        f"CSV '{csv_file.name}' accepted for campaign '{campaign.name}' "
                        f"as batch #{batch.batch_number}."
                    ),
                )
                return HttpResponseRedirect(
                    reverse("admin:charity_campaign_change", args=[campaign.pk])
                )
        else:
            form = AdminCampaignCSVUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": campaign,
            "title": f"Upload CSV for {campaign.name}",
            "form": form,
            "change_url": reverse("admin:charity_campaign_change", args=[campaign.pk]),
            "media": self.media + form.media,
        }
        return TemplateResponse(request, "admin/charity/campaign/upload_csv.html", context)

    @admin.display(description="Campaign CSV Upload")
    def upload_csv_action(self, obj: Campaign | None):
        if not obj or not obj.pk:
            return "Save the campaign before uploading a CSV batch."

        upload_url = reverse("admin:charity_campaign_upload_csv", args=[obj.pk])
        return format_html(
            '<a href="{}" style="display:inline-block;padding:8px 14px;border-radius:6px;'
            'background:#2563eb;color:#fff;text-decoration:none;font-weight:600;">'
            "Upload CSV Batch"
            "</a>",
            upload_url,
        )

    def get_fieldsets(self, request: HttpRequest, obj: object = None):
        mode = obj.campaign_mode if obj else None
        fieldsets = list(self._BASE_FIELDSETS)

        if obj and obj.pk:
            fieldsets.append(
                (
                    "CSV Upload",
                    {
                        "description": (
                            "Upload a donor CSV directly into this campaign from Django admin."
                        ),
                        "fields": ("upload_csv_action",),
                    },
                )
            )

        email_settings = (
            "Email Settings",
            {
                "classes": ("collapse",),
                "fields": ("from_email", "email_subject", "email_body", "email_thumbnail"),
            },
        )

        if mode == Campaign.CampaignMode.VDM:
            fieldsets += [
                email_settings,
                (
                    "Video Assets",
                    {
                        "classes": ("collapse",),
                        "description": "One shared video is sent to every donor in the batch.",
                        "fields": ("vdm_video", "cf_stream_video_id", "cf_stream_video_url"),
                    },
                ),
            ]
        elif mode == Campaign.CampaignMode.THANK_YOU_PERSONALIZED:
            fieldsets += [
                email_settings,
                (
                    "Video Assets",
                    {
                        "classes": ("collapse",),
                        "description": (
                            "A unique TTS voiceover is generated per donor and stitched onto the base video."
                        ),
                        "fields": ("base_video", "voiceover_script", "voice_id"),
                    },
                ),
                (
                    "Gratitude Card",
                    {
                        "classes": ("collapse",),
                        "description": (
                            "Sent to repeat donors who give again within the cooldown window "
                            "instead of generating a full new personalised video."
                        ),
                        "fields": ("gratitude_video", "gratitude_cooldown_days"),
                    },
                ),
            ]
        elif mode == Campaign.CampaignMode.THANK_YOU_STANDARD:
            fieldsets += [
                email_settings,
                (
                    "Video Assets",
                    {
                        "classes": ("collapse",),
                        "description": "One pre-rendered video is sent to all donors.",
                        "fields": ("base_video",),
                    },
                ),
                (
                    "Gratitude Card",
                    {
                        "classes": ("collapse",),
                        "description": (
                            "Sent to repeat donors who give again within the cooldown window."
                        ),
                        "fields": ("gratitude_video", "gratitude_cooldown_days"),
                    },
                ),
            ]
        else:
            # No mode set (new campaign) — show all fields with explanation
            fieldsets += [
                (
                    "Email Settings",
                    {
                        "classes": ("collapse",),
                        "fields": (
                            "from_email",
                            "email_subject",
                            "email_body",
                            "email_thumbnail",
                        ),
                    },
                ),
                (
                    "Video Assets",
                    {
                        "classes": ("collapse",),
                        "description": (
                            "All video fields are shown until a campaign mode is selected. "
                            "Save a mode above then re-open to see only the relevant fields."
                        ),
                        "fields": (
                            "vdm_video",
                            "cf_stream_video_id",
                            "cf_stream_video_url",
                            "base_video",
                            "voiceover_script",
                            "voice_id",
                            "gratitude_video",
                            "gratitude_cooldown_days",
                        ),
                    },
                ),
            ]

        fieldsets.append(self._CTA_FIELDSET)
        return fieldsets


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
