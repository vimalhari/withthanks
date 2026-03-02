from celery.result import AsyncResult
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from charity.api.serializers import BulkDonationIngestSerializer, DonationIngestSerializer
from charity.models import Charity
from charity.tasks import dispatch_donation_video_task


class DonationIngestAPIView(APIView):
    """
    Accept a single donation and dispatch video generation asynchronously.

    Returns a Celery task ID so the caller can poll for completion.
    """

    def post(self, request):
        serializer = DonationIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        # Validate charity exists (fast-fail before queuing)
        charity = Charity.objects.get(id=payload["charity_id"])

        result = dispatch_donation_video_task.apply_async(
            kwargs={
                "charity_id": charity.id,
                "donor_email": payload["donor_email"],
                "donor_name": payload["donor_name"],
                "amount": str(payload["amount"]),
                "donated_at": payload["donated_at"].isoformat() if payload.get("donated_at") else None,
                "source": "API",
                "campaign_type": payload["campaign_type"],
            },
        )

        return Response(
            {
                "task_id": result.id,
                "status": "queued",
                "donor_email": payload["donor_email"],
            },
            status=status.HTTP_202_ACCEPTED,
        )


class BulkDonationIngestAPIView(APIView):
    """
    Accept multiple donations and dispatch video generation asynchronously.

    Returns a list of Celery task IDs.
    """

    def post(self, request):
        serializer = BulkDonationIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tasks = []
        for payload in serializer.validated_data["donations"]:
            charity = Charity.objects.get(id=payload["charity_id"])

            result = dispatch_donation_video_task.apply_async(
                kwargs={
                    "charity_id": charity.id,
                    "donor_email": payload["donor_email"],
                    "donor_name": payload["donor_name"],
                    "amount": str(payload["amount"]),
                    "donated_at": payload["donated_at"].isoformat() if payload.get("donated_at") else None,
                    "source": "API",
                    "campaign_type": payload["campaign_type"],
                },
            )
            tasks.append(
                {
                    "task_id": result.id,
                    "donor_email": payload["donor_email"],
                    "status": "queued",
                }
            )

        return Response({"tasks": tasks}, status=status.HTTP_202_ACCEPTED)


class TaskStatusAPIView(APIView):
    """
    Poll the status of an async donation dispatch task.

    Returns the task state and, when complete, the dispatch result.
    """

    def get(self, request, task_id):
        result = AsyncResult(task_id)

        payload = {
            "task_id": task_id,
            "status": result.state,
        }

        if result.successful():
            payload["result"] = result.result
        elif result.failed():
            payload["error"] = str(result.result)

        return Response(payload)
