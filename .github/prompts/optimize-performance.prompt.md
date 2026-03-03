---
description: "Optimize database queries and performance in WithThanks"
---

# Performance Optimization

Analyze and optimize performance in the WithThanks codebase.

## Database Query Optimization

### N+1 Query Detection
Look for loops that access related objects without prefetching:
```python
# BAD — N+1 queries
for job in DonationJob.objects.filter(charity=charity):
    print(job.donation_batch.batch_number)  # Extra query per iteration

# GOOD — 1 query with join
for job in DonationJob.objects.filter(charity=charity).select_related("donation_batch"):
    print(job.donation_batch.batch_number)
```

### Prefetch for Reverse Relations
```python
# GOOD — prefetch reverse FK / M2M
charities = Charity.objects.prefetch_related("charitymember_set", "donationbatch_set")
```

### Aggregation Over Python Loops
```python
# BAD
total = sum(job.donation_amount for job in jobs)

# GOOD
from django.db.models import Sum
total = jobs.aggregate(total=Sum("donation_amount"))["total"]
```

### Use .only() / .defer() for Large Models
```python
# Only load needed columns for list views
DonationJob.objects.filter(charity=charity).only("id", "donor_name", "status", "created_at")
```

## Celery Task Performance
- Use `select_related` when loading objects in tasks.
- Clean up temporary files immediately after processing.
- Respect time limits: soft=25min, hard=30min.
- Use task `countdown` for retries to avoid thundering herd.

## Template Performance
- Minimize template tag calls in loops.
- Use `{% with %}` to cache expensive computations.
- Paginate list views (use `django.core.paginator.Paginator`).

## Caching Strategies
- Use Redis for caching (already available as Celery broker).
- Cache expensive aggregation queries.
- Use ETags/Last-Modified for API responses where appropriate.

## Profiling Commands
```bash
# Django debug toolbar (add to dev dependencies if needed)
# Check slow queries in logs (LOGGING configured for charity app at DEBUG level)
make dev  # Watch console for query logs
```
