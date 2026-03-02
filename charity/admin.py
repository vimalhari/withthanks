from django.contrib import admin
from .models import Charity, DonationJob, DonationBatch, UnsubscribedUser, Invoice, InvoiceBatch


# Register your models here.
admin.site.register(Charity)
admin.site.register(DonationBatch)

@admin.register(DonationJob)
class DonationJobAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "amount", "status", "created_at", "completed_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email", "task_id")

@admin.register(UnsubscribedUser)
class UnsubscribedUserAdmin(admin.ModelAdmin):
    list_display = ('email', 'reason', 'unsubscribed_from_job', 'ip_address', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('email', 'reason')
    readonly_fields = ('email', 'created_at', 'ip_address', 'user_agent', 'unsubscribed_from_job')
    ordering = ('-created_at',)
    
    def has_add_permission(self, request):
        # Prevent manual addition through admin
        return False
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion to maintain audit trail
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'charity', 'amount', 'status', 'issue_date', 'due_date', 'created_at')
    list_filter = ('status', 'invoice_type', 'issue_date')
    search_fields = ('invoice_number', 'charity__name')
    readonly_fields = ('created_at',)
    ordering = ('-issue_date',)


@admin.register(InvoiceBatch)
class InvoiceBatchAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'batch', 'videos_count', 'views_count', 'line_amount')
    list_filter = ('invoice__status',)
    search_fields = ('invoice__invoice_number', 'batch__batch_number')
