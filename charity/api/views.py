from celery import chain, chord, group
from celery.result import AsyncResult
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from charity.api.serializers import BulkDonationIngestSerializer, DonationIngestSerializer
from charity.models import Campaign, DonationBatch, DonationJob
from charity.permissions import IsCharityMember
from charity.tasks import (
    dispatch_email_for_job,
    generate_video_for_job,
    on_batch_complete,
    validate_and_prep_job,
)
from charity.utils.access_control import get_accessible_jobs, get_authorized_charity


def _resolve_campaign(charity, campaign_type):
    """Return the first active campaign matching *campaign_type*, or None."""
    if campaign_type == "VDM":
        mode_filter = {"campaign_mode": Campaign.CampaignMode.VDM}
    else:  # THANK_YOU
        mode_filter = {
            "campaign_mode__in": [
                Campaign.CampaignMode.THANK_YOU_PERSONALIZED,
                Campaign.CampaignMode.THANK_YOU_STANDARD,
            ]
        }
    return (
        Campaign.objects.accepting_donations()
        .filter(
            charity=charity,
            **mode_filter,
        )
        .first()
    )


class DonationIngestAPIView(APIView):
    """
    Accept a single donation and dispatch video generation asynchronously
    via the unified DonationJob pipeline.

    Returns the Celery task ID and DonationJob ID so the caller can poll
    for completion either via the task result or the job record.
    """

    permission_classes = [IsCharityMember]

    def post(self, request):
        serializer = DonationIngestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        charity = get_authorized_charity(request.user, payload["charity_id"])
        if charity is None:
            raise Http404
        campaign = _resolve_campaign(charity, payload["campaign_type"])

        batch = DonationBatch.objects.create(
            charity=charity,
            campaign=campaign,
            batch_number=DonationBatch.get_next_batch_number(charity),
            campaign_name=f"API \u2014 {payload['campaign_type']}",
            status=DonationBatch.BatchStatus.PROCESSING,
        )

        job = DonationJob.objects.create(
            donor_name=payload["donor_name"],
            donor_title=payload.get("donor_title", ""),
            donor_first_name=payload.get("donor_first_name", ""),
            donor_last_name=payload.get("donor_last_name", ""),
            email=payload["donor_email"],
            donation_amount=payload["amount"],
            status="pending",
            charity=charity,
            campaign=campaign,
            donation_batch=batch,
        )

        task_result = chain(
            validate_and_prep_job.s(job.id).set(queue="default"),
            generate_video_for_job.s().set(queue="video"),
            dispatch_email_for_job.s().set(queue="default"),
        ).apply_async()

        return Response(
            {
                "task_id": task_result.id if task_result is not None else None,
                "job_id": job.id,
                "batch_id": batch.id,
                "status": "queued",
                "donor_email": payload["donor_email"],
            },
            status=status.HTTP_202_ACCEPTED,
        )


class BulkDonationIngestAPIView(APIView):
    """
    Accept multiple donations and dispatch video generation asynchronously
    via a unified group + chord so the batch is tracked atomically.

    Returns the batch ID, chord task ID, and per-donation job IDs.
    """

    permission_classes = [IsCharityMember]

    def post(self, request):
        serializer = BulkDonationIngestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        # Group all donations by charity + campaign_type so they land in the
        # same batch where possible.
        donations = serializer.validated_data["donations"]
        if not donations:
            return Response({"jobs": []}, status=status.HTTP_202_ACCEPTED)

        # Use the first donation's charity/campaign_type as the batch key
        # (the serializer should validate homogeneity; mixed batches remain
        # supported via separate API calls).
        first = donations[0]
        charity = get_authorized_charity(request.user, first["charity_id"])
        if charity is None:
            raise Http404
        campaign = _resolve_campaign(charity, first["campaign_type"])

        batch = DonationBatch.objects.create(
            charity=charity,
            campaign=campaign,
            batch_number=DonationBatch.get_next_batch_number(charity),
            campaign_name=f"API Bulk \u2014 {first['campaign_type']}",
            status=DonationBatch.BatchStatus.PROCESSING,
        )

        # All donations share the same charity/campaign (validated by serializer).
        jobs_to_create = [
            DonationJob(
                donor_name=d["donor_name"],
                donor_title=d.get("donor_title", ""),
                donor_first_name=d.get("donor_first_name", ""),
                donor_last_name=d.get("donor_last_name", ""),
                email=d["donor_email"],
                donation_amount=d["amount"],
                status="pending",
                charity=charity,
                campaign=campaign,
                donation_batch=batch,
            )
            for d in donations
        ]
        created_jobs = DonationJob.objects.bulk_create(jobs_to_create)
        job_ids = [j.id for j in created_jobs]

        header = group(
            chain(
                validate_and_prep_job.s(jid).set(queue="default"),
                generate_video_for_job.s().set(queue="video"),
                dispatch_email_for_job.s().set(queue="default"),
            )
            for jid in job_ids
        )
        callback = on_batch_complete.s(batch_id=batch.id).set(queue="default")
        chord_result = chord(header)(callback)

        return Response(
            {
                "batch_id": batch.id,
                "chord_task_id": chord_result.id,
                "job_count": len(job_ids),
                "job_ids": job_ids,
                "status": "queued",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class TaskStatusAPIView(APIView):
    """
    Poll the status of an async task or a DonationJob.

    - Pass a Celery task_id to get raw task state.
    - Pass a job_id query param to get the DonationJob status from the DB.
    """

    permission_classes = [IsCharityMember]

    def get(self, request, task_id):
        # If a job_id is provided, serve the DB record (more reliable than
        # Redis task state which expires after CELERY_RESULT_EXPIRES).
        job_id = request.query_params.get("job_id")
        if job_id:
            try:
                job = get_accessible_jobs(request.user).get(id=job_id)
                return Response(
                    {
                        "job_id": job.id,
                        "status": job.status,
                        "donor_email": job.email,
                        "error_message": job.error_message,
                        "completed_at": job.completed_at,
                    }
                )
            except DonationJob.DoesNotExist:
                return Response({"error": "Job not found"}, status=status.HTTP_404_NOT_FOUND)

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
