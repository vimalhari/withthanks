# forms.py
from django import forms

from .models import Campaign, CharityMember, Invoice


class CSVUploadForm(forms.Form):
    csv_file = forms.FileField(label="Upload CSV")


class AdminCampaignCSVUploadForm(forms.Form):
    csv_file = forms.FileField(
        label="Campaign CSV file",
        help_text="Upload a donor CSV for this campaign.",
        widget=forms.FileInput(attrs={"accept": ".csv"}),
    )


class CharityMemberForm(forms.ModelForm):
    class Meta:
        model = CharityMember
        fields = ["role", "status"]


class AddMemberForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "saas-input", "placeholder": "Username"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "saas-input", "placeholder": "Email"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "saas-input", "placeholder": "Initial Password"})
    )
    role = forms.ChoiceField(choices=CharityMember.ROLE_CHOICES)


class InvoiceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamic queryset to avoid circular imports at module level
        from .models import Charity

        self.fields["charity"].queryset = Charity.objects.all()
        self.fields["campaign"].queryset = Campaign.objects.all()

    class Meta:
        model = Invoice
        fields = [
            "charity",
            "campaign",
            "period_start",
            "period_end",
            "status",
            "invoice_type",
            "billing_email",
            "additional_billing_emails",
            "notes",
        ]
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date", "class": "fin-input"}),
            "period_end": forms.DateInput(attrs={"type": "date", "class": "fin-input"}),
            "billing_email": forms.EmailInput(attrs={"class": "fin-input"}),
            "additional_billing_emails": forms.TextInput(
                attrs={
                    "class": "fin-input",
                    "placeholder": "cc@example.com, finance@example.com",
                }
            ),
            "notes": forms.Textarea(attrs={"class": "fin-textarea", "rows": 3}),
        }


class InvoiceStep1Form(forms.Form):
    charity = forms.ModelChoiceField(
        queryset=None, widget=forms.Select(attrs={"class": "form-select"})
    )
    campaign = forms.ModelChoiceField(
        queryset=None, widget=forms.Select(attrs={"class": "form-select"})
    )
    billing_start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    billing_end_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    payment_due_days = forms.IntegerField(
        initial=30, widget=forms.NumberInput(attrs={"class": "form-control"})
    )
    billing_email = forms.EmailField(
        required=False, widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    billing_address = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 3})
    )

    def __init__(self, *args, **kwargs):
        charity = kwargs.pop("charity", None)
        super().__init__(*args, **kwargs)
        from .models import Charity

        self.fields["charity"].queryset = Charity.objects.all()
        if charity:
            self.fields["charity"].initial = charity
            self.fields["campaign"].queryset = Campaign.objects.filter(charity=charity)
        else:
            self.fields["campaign"].queryset = Campaign.objects.all()


class InvoiceStep2Form(forms.Form):
    setup_costs = forms.FloatField(
        initial=0, widget=forms.NumberInput(attrs={"class": "form-control"})
    )
    csv_file_qty = forms.IntegerField(
        initial=0, widget=forms.NumberInput(attrs={"class": "form-control"})
    )
    vdm_package = forms.ChoiceField(
        choices=[
            ("none", "None"),
            ("standard", "Standard"),
            ("charity_supplied", "Charity Supplied"),
        ],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    enable_gratitude_card = forms.BooleanField(
        required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )
    video_stock_cost = forms.FloatField(
        initial=0, widget=forms.NumberInput(attrs={"class": "form-control"})
    )
    audio_stock_cost = forms.FloatField(
        initial=0, widget=forms.NumberInput(attrs={"class": "form-control"})
    )

    # Optional services
    enable_email_sign_off = forms.BooleanField(required=False)
    enable_pers_vo_amends = forms.BooleanField(required=False)
    enable_text_amends = forms.BooleanField(required=False)
    enable_re_proof = forms.BooleanField(required=False)
    enable_add_programming = forms.BooleanField(required=False)
    enable_data_cleaning = forms.BooleanField(required=False)
    enable_audio_cleanup = forms.BooleanField(required=False)
    enable_analytics_report = forms.BooleanField(required=False)
    enable_bounce_log = forms.BooleanField(required=False)
    enable_bounce_foc = forms.BooleanField(required=False)
    enable_qr_generation = forms.BooleanField(required=False)
    enable_batch_processing = forms.BooleanField(required=False)
    enable_add_donate_page = forms.BooleanField(required=False)
