from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from charity.models import Campaign, Charity


class DonationIngestSerializer(serializers.Serializer):
    charity_id = serializers.IntegerField()
    donor_email = serializers.EmailField()
    donor_name = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    donated_at = serializers.DateTimeField(required=False)
    campaign_type = serializers.ChoiceField(
        choices=Campaign.CampaignType.choices,
        default=Campaign.CampaignType.THANK_YOU,
    )

    def validate_charity_id(self, value):
        if not Charity.objects.filter(id=value).exists():
            raise serializers.ValidationError("Invalid charity_id.")
        return value

    def validate_amount(self, value: Decimal):
        if value <= 0:
            raise serializers.ValidationError("amount must be greater than 0.")
        return value

    def validate(self, attrs):
        attrs.setdefault("donated_at", timezone.now())
        return attrs


class BulkDonationIngestSerializer(serializers.Serializer):
    donations = DonationIngestSerializer(many=True)
