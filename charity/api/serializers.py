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

    def validate_donations(self, donations):
        """All donations in a bulk request must share the same charity and campaign_type."""
        if not donations:
            return donations
        first_charity = donations[0]["charity_id"]
        first_type = donations[0]["campaign_type"]
        for i, d in enumerate(donations[1:], start=1):
            if d["charity_id"] != first_charity:
                raise serializers.ValidationError(
                    f"Donation at index {i} has charity_id={d['charity_id']} "
                    f"but index 0 has charity_id={first_charity}. "
                    "Mixed-charity bulk requests are not supported — send separate requests per charity."
                )
            if d["campaign_type"] != first_type:
                raise serializers.ValidationError(
                    f"Donation at index {i} has campaign_type={d['campaign_type']} "
                    f"but index 0 has campaign_type={first_type}. "
                    "Mixed campaign_type bulk requests are not supported."
                )
        return donations
