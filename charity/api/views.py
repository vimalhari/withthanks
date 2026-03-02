from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from charity.api.serializers import BulkDonationIngestSerializer, DonationIngestSerializer
from charity.models import Charity
from charity.services.video_dispatch import dispatch_donation_video


class DonationIngestAPIView(APIView):
    def post(self, request):
        serializer = DonationIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        charity = Charity.objects.get(id=payload["charity_id"])
        result = dispatch_donation_video(
            charity=charity,
            donor_email=payload["donor_email"],
            donor_name=payload["donor_name"],
            amount=payload["amount"],
            donated_at=payload["donated_at"],
            source="API",
            campaign_type=payload["campaign_type"],
        )

        return Response(
            {
                "donation_id": result.donation_id,
                "send_log_id": result.send_log_id,
                "donor_email": result.donor_email,
                "send_kind": result.send_kind,
                "campaign_type": result.campaign_type,
                "video_path": result.video_path,
            },
            status=status.HTTP_201_CREATED,
        )


class BulkDonationIngestAPIView(APIView):
    def post(self, request):
        serializer = BulkDonationIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        results = []
        for payload in serializer.validated_data["donations"]:
            charity = Charity.objects.get(id=payload["charity_id"])
            result = dispatch_donation_video(
                charity=charity,
                donor_email=payload["donor_email"],
                donor_name=payload["donor_name"],
                amount=payload["amount"],
                donated_at=payload["donated_at"],
                source="API",
                campaign_type=payload["campaign_type"],
            )
            results.append(
                {
                    "donation_id": result.donation_id,
                    "send_log_id": result.send_log_id,
                    "donor_email": result.donor_email,
                    "send_kind": result.send_kind,
                    "campaign_type": result.campaign_type,
                    "video_path": result.video_path,
                }
            )

        return Response({"results": results}, status=status.HTTP_201_CREATED)
