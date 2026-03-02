import logging
import random

from django.db import transaction

from ..models import DonationBatch

logger = logging.getLogger(__name__)


def simulate_batch_engagement(batch_id, min_val=100, max_val=1000):
    """
    Simulate views and clicks for all jobs in a batch.
    Used for demonstration/simulated performance metrics.
    """
    try:
        with transaction.atomic():
            batch = DonationBatch.objects.get(id=batch_id)
            jobs = batch.jobs.all()

            for job in jobs:
                # Randomize fake views and clicks
                job.fake_views = random.randint(min_val, max_val)
                # Clicks are usually a fraction of views
                job.fake_clicks = random.randint(0, max(1, job.fake_views // 10))
                job.save(update_fields=["fake_views", "fake_clicks"])

            logger.info(
                f"📊 Simulated engagement for batch {batch_id}: {jobs.count()} jobs updated."
            )

    except DonationBatch.DoesNotExist:
        logger.error(f"Simulation failed: Batch {batch_id} not found.")
    except Exception as e:
        logger.exception(f"Error during metrics simulation for batch {batch_id}: {e}")
