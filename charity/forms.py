# forms.py
from django import forms

from charity.models import Campaign, Charity


class CSVUploadForm(forms.Form):
    charity = forms.ModelChoiceField(queryset=Charity.objects.all(), empty_label=None)
    campaign_type = forms.ChoiceField(
        choices=Campaign.CampaignType.choices,
        initial=Campaign.CampaignType.THANK_YOU,
    )
    csv_file = forms.FileField(label="Upload CSV")
