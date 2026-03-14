# WithThanks

A Django web application that helps charities send personalised thank-you videos to their donors. When a donation is received, WithThanks generates a voiceover using ElevenLabs TTS, stitches it onto a branded base video with FFmpeg, and delivers it to the donor via email. Both the REST API and the CSV batch upload path share a single unified Celery pipeline — every job is tracked through a `DonationJob` record, batch completion is reported atomically via Celery chords, and three isolated worker queues prevent slow video jobs from ever blocking maintenance tasks.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Local Setup](#local-setup)
  - [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
  - [Using Docker Compose](#using-docker-compose)
  - [Without Docker](#without-docker)
  - [Development Tooling](#development-tooling)
- [Celery Pipeline](#celery-pipeline)
- [API Reference](#api-reference)
- [CSV Upload](#csv-upload)
- [CI/CD Pipeline](#cicd-pipeline)
- [Models Overview](#models-overview)

---

## Features

- **Personalised thank-you videos** — generates a unique video per donor using ElevenLabs TTS voiceovers stitched onto a base video with FFmpeg.
- **Multiple send modes** — `WithThanks` (personalised or card-only fallback) and `VDM` (shared campaign video for CSV-driven mass campaigns).
- **30-day deduplication** — donors who already received a personalised video in the last 30 days get a "card only" fallback to avoid over-messaging.
- **CSV batch processing** — upload a CSV to trigger video generation for many donors at once; the whole batch is tracked as a single `DonationBatch` and marked `completed` or `completed_with_errors` automatically.
- **REST API** — single and bulk donation ingestion endpoints for external donation platforms. The API accepts `THANK_YOU` jobs; `VDM` is intentionally restricted to CSV batch upload.
- **Unified Celery pipeline** — both API and CSV jobs flow through the same 3-stage `DonationJob` pipeline: validate → generate → dispatch. Groups + chords provide atomic batch completion tracking for batches.
- **Queue isolation** — `video` queue (CPU/FFmpeg), `default` queue (orchestration/callbacks), and `maintenance` queue (periodic tasks) run on separate workers.
- **Cloudflare Stream** — VDM campaign videos are uploaded once per campaign and the CDN URL is cached. If Stream is unavailable, email links fall back to a public storage-backed media URL instead of a worker-local temp path.
- **Resend email delivery** — personalised HTML emails with embedded video links sent via the Resend API.
- **Admin notifications** — when a batch finishes, an email is sent to `ADMIN_NOTIFICATION_EMAIL` with job totals and pass/fail counts.
- **Multi-tenant** — each charity has its own campaigns, templates, member users, and job history; superadmin can switch context.
- **Billing** — Internal invoicing with PDF export and email delivery.
- **Django Admin** — full admin interface for managing charities, campaigns, donors, donations, invoices, and send logs.

---

## Architecture Overview

The API and CSV paths converge on the same `DonationJob`-based pipeline.
The API is used for `THANK_YOU` jobs, while `VDM` is a CSV-only campaign flow.
Batch fan-outs use Celery `group + chord` so every batch has an atomic
completion callback.

```
Donation event
     ┌────────────┴────────────┐
     │                         │
    REST API                CSV batch upload
    THANK_YOU only          THANK_YOU or VDM
    POST /api/donations/*   POST /upload/
     │                         │
     ▼                         ▼
Create DonationBatch      batch_process_csv
+ DonationJob(s)          (bulk_create all rows)
     │                         │
     └──────────┬──────────────┘
                │
      chain(validate, generate, dispatch)
      per job / grouped under a chord for batches
      │
                ▼
    DonationJob pipeline
                │
      ┌───────────┴──────────────┐
      │                          │
    Mode:VDM                Mode:WithThanks
    (shared campaign        (personalised TTS +
     video / cached)         FFmpeg or card-only)
      │                          │
      ▼                          ▼
  Cloudflare Stream       ElevenLabs + FFmpeg
  or storage-backed URL     when personalised
                │
                ▼
    send_video_email() → Resend
                │
                ▼
         job.status = "success"
                │
                ▼ (chord callback)
       on_batch_complete()  [default queue]
       → DonationBatch.status = completed
       → admin notification email
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Django 6.0.2 |
| REST API | Django REST Framework 3.16.1 |
| Task queue | Celery 5.6 + Redis 7 (group / chord / queue routing) |
| Video processing | FFmpeg (subprocess) |
| TTS / Voiceover | ElevenLabs 2.37 |
| Video hosting | Cloudflare Stream |
| Email delivery | Resend 2.23 |
| Object storage | Cloudflare R2 (S3-compatible via `boto3` + `django-storages`) |
| Billing | Internal invoicing (PDF + Resend) |
| Scheduled tasks | Celery Beat (`django-celery-beat`) |
| Database (dev) | SQLite |
| Database (prod) | PostgreSQL 17 (psycopg 3.3) |
| Containerisation | Docker (built with uv) |
| Package manager | uv 0.10 |
| Linter / formatter | Ruff 0.15 |
| Type checker | Pyright 1.1.408 |
| CI | GitHub Actions |
| CD | Coolify (Hetzner = dev · DigitalOcean = prod) |

---

## Project Structure

```
WithThanks/
├── charity/                    # Main Django application
│   ├── models.py               # Charity, Campaign, DonationBatch, DonationJob, Donor, ...
│   ├── tasks.py                # Celery tasks: validate_and_prep_job,
│   │                           #   generate_video_for_job, dispatch_email_for_job,
│   │                           #   batch_process_csv, on_batch_complete,
│   │                           #   and periodic maintenance tasks
│   ├── views.py                # General views (dashboard, profile, etc.)
│   ├── views_batches.py        # CSV upload, campaign blast, send wizard
│   ├── views_billing.py        # Invoice billing views
│   ├── views_campaign.py       # Campaign CRUD
│   ├── views_analytics.py      # Analytics views
│   ├── forms.py                # Django forms
│   ├── admin.py                # Django Admin configuration
│   ├── urls.py                 # URL routing
│   ├── api/
│   │   ├── views.py            # DonationIngestAPIView, BulkDonationIngestAPIView,
│   │   │                       #   TaskStatusAPIView (now DonationJob-backed)
│   │   └── serializers.py      # DonationIngestSerializer, BulkDonationIngestSerializer
│   ├── services/
│   │   ├── video_build_service.py    # TTS + FFmpeg stitching
│   │   ├── video_pipeline_service.py # Cloudflare Stream + public URL resolution
│   │   └── sync_bridge.py            # Sync DonationJob → normalised Donor/Donation/VideoSendLog
│   ├── utils/
│   │   ├── video_utils.py      # FFmpeg stitching helpers
│   │   ├── voiceover.py        # ElevenLabs TTS wrapper
│   │   ├── cloudflare_stream.py# Cloudflare Stream upload helper
│   │   ├── resend_utils.py     # Resend email helper
│   │   └── access_control.py   # Multi-tenant access helpers
│   ├── management/commands/    # Custom management commands
│   ├── migrations/             # Database migrations
│   └── templates/              # HTML templates
├── withthanks/                 # Django project configuration
│   ├── settings.py             # All settings incl. CELERY_TASK_QUEUES / CELERY_TASK_ROUTES
│   ├── celery.py               # Celery app + Beat schedule (queue-aware)
│   ├── urls.py
│   └── wsgi.py
├── media/
│   ├── base_videos/            # Base MP4 templates
│   ├── outputs/                # Generated / stitched output videos
│   └── voiceover_cache/        # Cached TTS audio files (pruned after 30 days)
├── .github/
│   └── workflows/
│       ├── ci.yml              # Ruff + Pyright + Django tests
│       ├── deploy-dev.yml      # Push to develop → Coolify on Hetzner
│       └── deploy-prod.yml     # Push to main → Coolify on DigitalOcean
├── Dockerfile                  # Multi-stage build (uv, Python 3.12)
├── docker-compose.yml          # Local dev: web + worker-video + worker-maintenance + beat + redis + db
├── entrypoint.sh
├── manage.py
├── pyproject.toml              # Single source of truth (uv, ruff, pyright)
├── uv.lock                     # Pinned dependency lockfile
└── requirements.txt            # Auto-generated: uv export --no-hashes --no-dev
```

---

## Getting Started

### Prerequisites

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/) — fast Python package and project manager
- FFmpeg installed and on `PATH`
- Redis (for Celery broker + result backend)
- Docker & Docker Compose (optional, recommended for local development)

### Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/vimalhari/withthanks.git
cd withthanks

# 2. Install dependencies and create the virtual environment (uv handles both)
uv sync

# 3. Copy the example environment file and fill in your values
cp .env.example .env

# 4. Apply database migrations
uv run python manage.py migrate

# 5. Create a superuser for the Django Admin
uv run python manage.py createsuperuser

# 6. Start the development server
uv run python manage.py runserver
```

### Environment Variables

Create a `.env` file in the project root. The minimum required set for local development:

```env
# Django
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=true

# Database (leave unset to use SQLite in development)
DATABASE_URL=postgres://user:password@localhost:5432/withthanks

# Media
MEDIA_ROOT=/app/media

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Video / delivery
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_STREAM_TOKEN=your-api-token
CLOUDFLARE_STREAM_ENABLED=true

# ElevenLabs TTS
ELEVENLABS_API_KEY=your-elevenlabs-api-key

# Resend (email)
RESEND_API_KEY=your-resend-api-key
DEFAULT_FROM_EMAIL=WithThanks <no-reply@yourdomain.com>

# Admin notifications — receives batch-completion emails (optional)
ADMIN_NOTIFICATION_EMAIL=admin@yourdomain.com

# Cloudflare R2 (optional — only needed if remote file storage is required)
CLOUDFLARE_R2_ACCESS_KEY_ID=your-r2-access-key
CLOUDFLARE_R2_SECRET_ACCESS_KEY=your-r2-secret-key
CLOUDFLARE_R2_BUCKET_NAME=your-bucket
CLOUDFLARE_R2_ACCOUNT_ID=your-account-id

# Public URL used in email tracking links and media fallbacks
SERVER_BASE_URL=http://127.0.0.1:8000

```

---

## Running the Application

### Using Docker Compose

The `docker-compose.yml` defines five services:

| Service | Purpose |
|---|---|
| `db` | PostgreSQL 17 |
| `redis` | Redis 7 (broker + result backend) |
| `web` | Django dev server (hot-reload, runs migrations on startup) |
| `worker` | Celery worker consuming `video` and `default` queues (concurrency 2) |
| `worker-maintenance` | Celery worker consuming `maintenance` queue only (concurrency 1) |
| `beat` | Celery Beat periodic task scheduler |

```bash
# Start all services
docker compose up

# Background mode
docker compose up -d

# Follow worker logs
docker compose logs -f worker
```

### Without Docker

Run each component in a separate terminal:

```bash
# Terminal 1: Django dev server
uv run python manage.py runserver

# Terminal 2: Celery worker — video + orchestration
uv run celery -A withthanks worker --loglevel=info --queues=video,default --concurrency=2

# Terminal 3: Celery worker — maintenance (beat tasks)
uv run celery -A withthanks worker --loglevel=info --queues=maintenance --concurrency=1

# Terminal 4: Celery Beat scheduler
uv run celery -A withthanks beat --loglevel=info
```

### Development Tooling

```bash
# Lint
uv run ruff check .

# Auto-fix lint issues
uv run ruff check --fix .

# Format
uv run ruff format .

# Type check
uv run pyright

# Run tests
uv run python manage.py test
```

---

## Celery Pipeline

### Queues

| Queue | Worker | Tasks routed here |
|---|---|---|
| `video` | `worker` | `generate_video_for_job` |
| `default` | `worker` | `validate_and_prep_job`, `dispatch_email_for_job`, `batch_process_csv`, `on_batch_complete` |
| `maintenance` | `worker-maintenance` | `refresh_all_campaign_stats`, `mark_overdue_invoices`, `cleanup_stale_jobs`, `prune_voiceover_cache`, `cleanup_old_videos` |

### Key tasks

| Task | Description |
|---|---|
| `validate_and_prep_job(job_id)` | Stage 1. Resolves mode, template, base asset, and the thank-you dedup/card-only decision. Runs on the `default` queue. |
| `generate_video_for_job(context)` | Stage 2. Builds personalised videos for `THANK_YOU` jobs or downloads the shared campaign asset for `VDM`. Runs on the `video` queue. |
| `dispatch_email_for_job(context)` | Stage 3. Uploads to Cloudflare Stream when applicable, resolves a public video URL, sends via Resend, and persists final job status. Runs on the `default` queue. |
| `batch_process_csv(batch_id)` | Reads CSV, bulk-creates `DonationJob` rows, and dispatches per-job validate → generate → dispatch chains under a `group + chord`. Fails fast for VDM campaigns that have no `vdm_video`. |
| `on_batch_complete(results, batch_id)` | Chord callback. Marks `DonationBatch.status` as `completed` or `completed_with_errors` and sends an admin notification email. |
| `refresh_all_campaign_stats` | Beat: every 15 min. Refreshes `CampaignStats` for all campaigns. |
| `mark_overdue_invoices` | Beat: daily 06:00 UTC. Transitions `Sent` invoices past due date to `Overdue`. |
| `cleanup_stale_jobs` | Beat: every 30 min. Resets jobs stuck in `processing` for more than 2 hours to `failed`. |
| `prune_voiceover_cache` | Beat: daily 03:00 UTC. Deletes cached TTS files older than 30 days. |
| `cleanup_old_videos` | Beat: daily 04:00 UTC. Deletes generated output videos older than 7 days. |

### Time limits

| Setting | Value |
|---|---|
| `CELERY_TASK_SOFT_TIME_LIMIT` | 25 min — triggers `SoftTimeLimitExceeded`, allowing graceful cleanup |
| `CELERY_TASK_TIME_LIMIT` | 30 min — hard SIGKILL if the soft limit is ignored |
| `CELERY_RESULT_EXPIRES` | 24 h — task results are auto-expired from Redis after one day |

---

## API Reference

All endpoints are prefix-routed under `/api/` (see `withthanks/urls.py`).

### `POST /api/donations/ingest/`

Trigger a thank-you video for a single donation.

`VDM` is not accepted on this endpoint. Use CSV batch upload for VDM campaigns.

**Request body:**

```json
{
  "charity_id": 1,
  "donor_email": "donor@example.com",
  "donor_name": "Jane Doe",
  "amount": "50.00",
  "donated_at": "2026-03-01T10:00:00Z",
  "campaign_type": "THANK_YOU"
}
```

**Response `202 Accepted`:**

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "job_id": 42,
  "batch_id": 7,
  "status": "queued",
  "donor_email": "donor@example.com"
}
```

### `POST /api/donations/bulk-ingest/`

Trigger videos for multiple donations. All jobs are tracked in one `DonationBatch`; a chord fires `on_batch_complete` when all jobs finish.

`VDM` is not accepted on this endpoint. Use CSV batch upload for VDM campaigns.

**Request body:**

```json
{
  "donations": [
    { "charity_id": 1, "donor_email": "alice@example.com", "donor_name": "Alice", "amount": "25.00", "campaign_type": "THANK_YOU" },
    { "charity_id": 1, "donor_email": "bob@example.com",   "donor_name": "Bob",   "amount": "100.00", "campaign_type": "THANK_YOU" }
  ]
}
```

**Response `202 Accepted`:**

```json
{
  "batch_id": 8,
  "chord_task_id": "b2c3d4e5-...",
  "job_count": 2,
  "job_ids": [43, 44],
  "status": "queued"
}
```

### `GET /api/tasks/<task_id>/`

Poll a Celery task by its ID. Optionally pass `?job_id=<id>` to get the
DB-sourced `DonationJob` status instead (more reliable after result expiry).

**Response (by task ID):**

```json
{ "task_id": "a1b2c3d4-...", "status": "SUCCESS", "result": { ... } }
```

**Response (by job ID — `?job_id=42`):**

```json
{
  "job_id": 42,
  "status": "success",
  "donor_email": "donor@example.com",
  "error_message": null,
  "completed_at": "2026-03-02T11:23:45Z"
}
```

---

## CSV Upload

Navigate to `/upload/` to access the CSV upload form.

**Accepted column names (case-insensitive, flexible synonyms supported):**

| Field | Accepted column names | Required |
|---|---|---|
| Email | `email`, `recipient email`, `email-id`, `email address` | Yes |
| Name | `donor_name`, `name`, `full name` | No (defaults to "Donor") |
| Amount | `donation_amount`, `amount`, `donation` | No (defaults to 0) |

**Example:**

```csv
email,name,amount
alice@example.com,Alice Smith,50.00
bob@example.com,Bob Jones,25.00
```

On submission:
1. A `DonationBatch` record is created with `status = pending`.
2. `batch_process_csv` runs in the background.
3. If the selected campaign is `VDM`, the batch fails fast unless the campaign has a `vdm_video` configured.
4. Valid rows are bulk-created as `DonationJob` records and fanned out via `group + chord`.
5. Each job runs through `validate_and_prep_job` → `generate_video_for_job` → `dispatch_email_for_job`.
6. VDM uploads the campaign video once to Cloudflare Stream and caches the playback URL on the campaign. If Stream is unavailable, donor links fall back to a public storage-backed media URL.
7. When all jobs finish, `on_batch_complete` marks the batch as `completed` or `completed_with_errors` and emails `ADMIN_NOTIFICATION_EMAIL`.

---

## CI/CD Pipeline

### Branching strategy

| Branch | Environment | Host |
|---|---|---|
| `develop` | Dev | Hetzner VPS |
| `main` | Production | DigitalOcean Droplet |

### Workflows

#### `.github/workflows/ci.yml` — every push / PR

1. **Ruff lint** — `ruff check .`
2. **Ruff format check** — `ruff format --check .`
3. **Pyright type check** — `pyright`
4. **Django tests** — `python manage.py test`

#### `.github/workflows/deploy-dev.yml` — push to `develop`

Triggers the Coolify **dev** application webhook on Hetzner via the `dev` GitHub Environment secrets (`COOLIFY_WEBHOOK_URL`, `COOLIFY_TOKEN`).

#### `.github/workflows/deploy-prod.yml` — push to `main`

Runs the full CI suite first, then triggers the Coolify **prod** application webhook on DigitalOcean.

### Required GitHub Environment secrets

| Secret | Description |
|---|---|
| `COOLIFY_WEBHOOK_URL` | Coolify deploy webhook URL |
| `COOLIFY_TOKEN` | Coolify API token |

| Variable | Description |
|---|---|
| `APP_URL` | Public URL of the deployed app |

---

## Models Overview

| Model | Description |
|---|---|
| `Charity` | A registered charity organisation linked to a Django `User` account. |
| `Campaign` | Links a charity to an appeal type (`THANK_YOU` or `VDM`), campaign media, template selection, and delivery settings. |
| `DonationBatch` | Groups a set of `DonationJob` records. Tracks `status` (`pending → processing → completed / completed_with_errors / failed`) and is the target of the Celery chord callback. |
| `DonationJob` | A single donor send job — tracks `status`, `video_path`, `generation_time`, `completed_at`, and `error_message`. The single source of truth for both API and CSV pipeline jobs. |
| `VideoTemplate` | An uploaded base video used as the canvas for FFmpeg stitching. |
| `TextTemplate` | A named voiceover script with ElevenLabs voice ID. Supports `{{donor_name}}`, `{{donation_amount}}`, `{{charity}}`, `{{campaign_name}}` placeholders. |
| `Donor` | Normalised donor record scoped to a charity (`unique_together: charity + email`). |
| `Donation` | A financial donation record linking `Donor`, `Charity`, amount, and campaign type. |
| `VideoSendLog` | Audit log of every video send attempt, including Cloudflare Stream metadata, Resend message ID, send kind, and error details. |
| `Invoice` | Invoice record with status lifecycle (`Draft → Sent → Paid / Overdue`). |
| `UnsubscribedUser` | Per-charity unsubscribe list; checked before every job is processed. |
