# WithThanks

A Django web application that helps charities send personalized thank-you videos to their donors. When a donation is received, WithThanks generates a voiceover using ElevenLabs TTS, stitches it onto a branded base video with FFmpeg, uploads the result to Cloudflare Stream, and delivers it to the donor via email.

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
  - [Using Docker](#using-docker)
  - [Without Docker](#without-docker)
- [API Reference](#api-reference)
- [CSV Upload](#csv-upload)
- [CI/CD Pipeline](#cicd-pipeline)
- [Models Overview](#models-overview)

---

## Features

- **Personalized thank-you videos** – generates a unique video per donor using ElevenLabs TTS voiceovers stitched onto a base video.
- **Gratitude video campaigns** – automatically sends a special "gratitude" video to repeat donors (configurable cooldown period).
- **CSV batch processing** – upload a CSV file to trigger video generation and delivery for many donors at once.
- **REST API** – single and bulk donation ingestion endpoints for integration with external donation platforms.
- **Cloudflare Stream** – videos are uploaded to Cloudflare Stream for reliable, low-latency playback; falls back to email attachments if disabled.
- **Resend email delivery** – donor emails are sent through the Resend API.
- **Multi-campaign support** – each charity can have multiple campaigns (Thank You, Direct Email) with separate video templates and text templates.
- **Django Admin** – full admin interface for managing charities, campaigns, donors, donations, and send logs.

---

## Architecture Overview

```
Donation event (CSV row or API call)
        │
        ▼
video_dispatch.dispatch_donation_video()
        │
        ├─► Resolve active Campaign for the given charity & campaign type
        ├─► Look up or create Donor record
        ├─► Create Donation record
        │
        ├─► Decide send kind:
        │     - GRATITUDE   (repeat donor within cooldown window)
        │     - TEMPLATE    (campaign has a video template, no personalisation)
        │     - PERSONALIZED (generate TTS voiceover → stitch video)
        │
        ├─► [Personalized / Gratitude] generate_voiceover() → ElevenLabs TTS
        ├─► stitch_voice_and_overlay() → FFmpeg
        │
        ├─► upload_video_to_stream() → Cloudflare Stream
        ├─► send_video_email() → Resend
        └─► Write VideoSendLog record
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Django 6.0.2 |
| REST API | Django REST Framework 3.16.1 |
| Task queue | Celery 5.6 + Redis 7.2 |
| Video processing | FFmpeg (via `ffmpeg-python`) |
| TTS / Voiceover | ElevenLabs 2.37 |
| Video hosting | Cloudflare Stream |
| Email delivery | Resend 2.23 |
| Object storage | Cloudflare R2 *(optional, S3-compatible via `boto3`)* |
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
│   ├── models.py               # Charity, Campaign, Donor, Donation, VideoSendLog, ...
│   ├── views.py                # CSV upload & processing view
│   ├── forms.py                # CSVUploadForm
│   ├── admin.py                # Django Admin configuration
│   ├── urls.py                 # URL routing
│   ├── api/
│   │   ├── views.py            # DonationIngestAPIView, BulkDonationIngestAPIView
│   │   └── serializers.py      # DonationIngestSerializer, BulkDonationIngestSerializer
│   ├── services/
│   │   └── video_dispatch.py   # Core orchestration logic
│   ├── utils/
│   │   ├── video_utils.py      # FFmpeg stitching helpers
│   │   ├── voiceover.py        # ElevenLabs TTS wrapper
│   │   ├── cloudflare_stream.py# Cloudflare Stream upload helper
│   │   ├── resend_utils.py     # Resend email helper
│   │   └── filenames.py        # Safe filename utilities
│   ├── management/commands/
│   │   └── generate_videos.py  # Custom management command (test/dev)
│   ├── migrations/             # Database migrations
│   └── templates/              # HTML templates (upload_csv, voiceovers_list, ...)
├── withthanks/                 # Django project configuration
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── media/
│   ├── base_videos/            # Base MP4 templates
│   ├── videos/                 # Generated / stitched output videos
│   └── voiceovers/             # Generated TTS audio files
├── .github/
│   └── workflows/
│       ├── ci.yml              # Ruff + Pyright + Django tests
│       ├── deploy-dev.yml      # Push to develop → Coolify on Hetzner
│       └── deploy-prod.yml     # Push to main → Coolify on DigitalOcean
├── Dockerfile                  # Multi-stage build (uv, Python 3.12)
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
- [uv](https://docs.astral.sh/uv/) – fast Python package and project manager
- FFmpeg installed and on `PATH`
- Redis (for Celery)
- Docker (optional, for containerised setup)

### Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/Rajachellan/WithThanks.git
cd WithThanks

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

Create a `.env` file in the project root with the following variables:

```env
# Django
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=true

# Database (leave unset to use SQLite in development)
DATABASE_URL=postgres://user:password@localhost:5432/withthanks

# Media
MEDIA_ROOT=/app/media

# Cloudflare Stream
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_STREAM_TOKEN=your-api-token
CLOUDFLARE_STREAM_ENABLED=true

# ElevenLabs
ELEVENLABS_API_KEY=your-elevenlabs-api-key

# Resend (email)
RESEND_API_KEY=your-resend-api-key

# Cloudflare R2 (optional — only needed if file storage is required)
# Install the r2 extra first: uv sync --extra r2
CLOUDFLARE_R2_ACCESS_KEY_ID=your-r2-access-key
CLOUDFLARE_R2_SECRET_ACCESS_KEY=your-r2-secret-key
CLOUDFLARE_R2_BUCKET_NAME=your-bucket
CLOUDFLARE_R2_ACCOUNT_ID=your-account-id

# Redis / Celery
CELERY_BROKER_URL=redis://localhost:6379/0
```

---

## Running the Application

### Using Docker

```bash
# Build and start
docker build -t withthanks-django:latest .
docker run -d \
  --name withthanks-container \
  -p 8000:8000 \
  -v /path/to/media:/app/media \
  --env-file .env \
  withthanks-django:latest
```

### Without Docker

```bash
# Terminal 1: Django dev server
uv run python manage.py runserver

# Terminal 2: Celery worker
uv run celery -A withthanks worker --loglevel=info
```

### Development tooling

```bash
# Lint
uv run ruff check .

# Auto-fix lint issues
uv run ruff check --fix .

# Format
uv run ruff format .

# Type check
uv run pyright
```

---

## API Reference

All API endpoints are prefix-routed under `/api/` (see `withthanks/urls.py`).

### `POST /api/donations/ingest/`

Trigger a thank-you video for a single donation.

**Request body:**

```json
{
  "charity_id": 1,
  "donor_email": "donor@example.com",
  "donor_name": "Jane Doe",
  "amount": "50.00",
  "donated_at": "2026-03-01T10:00:00Z",   // optional, defaults to now
  "campaign_type": "THANK_YOU"             // THANK_YOU | DIRECT_EMAIL
}
```

**Response `201 Created`:**

```json
{
  "donation_id": 42,
  "send_log_id": 7,
  "donor_email": "donor@example.com",
  "send_kind": "PERSONALIZED",
  "campaign_type": "THANK_YOU",
  "video_path": "/app/media/videos/jane_doe_thankyou.mp4"
}
```

---

### `POST /api/donations/bulk-ingest/`

Trigger thank-you videos for multiple donations in a single request.

**Request body:**

```json
{
  "donations": [
    {
      "charity_id": 1,
      "donor_email": "donor1@example.com",
      "donor_name": "Alice",
      "amount": "25.00",
      "campaign_type": "THANK_YOU"
    },
    {
      "charity_id": 1,
      "donor_email": "donor2@example.com",
      "donor_name": "Bob",
      "amount": "100.00",
      "campaign_type": "DIRECT_EMAIL"
    }
  ]
}
```

---

## CSV Upload

Navigate to `/upload/` in the browser to access the CSV upload form.

**Required CSV columns:**

| Column | Required | Description |
|---|---|---|
| `email` | Yes | Donor email address |
| `name` | No | Donor full name (defaults to "donor") |
| `amount` | Yes | Donation amount (numeric) |
| `donated_at` | No | ISO 8601 datetime string |

**Example:**

```csv
email,name,amount,donated_at
alice@example.com,Alice Smith,50.00,2026-03-01T09:00:00Z
bob@example.com,Bob Jones,25.00,2026-03-01T10:30:00Z
```

Select the target charity and campaign type in the form, then submit. Each row dispatches a video generation and email delivery job. Processing errors are reported per-row without halting the rest of the batch.

---

## CI/CD Pipeline

The project uses **GitHub Actions** for CI and **Coolify** for CD across two environments.

### Branching strategy

| Branch | Environment | Host |
|---|---|---|
| `develop` | Dev | Hetzner VPS |
| `main` | Production | DigitalOcean Droplet |

### Workflows

#### `.github/workflows/ci.yml` — runs on every push / PR

1. **Ruff lint** – `ruff check .`
2. **Ruff format check** – `ruff format --check .`
3. **Pyright type check** – `pyright`
4. **Django tests** – `python manage.py test`

#### `.github/workflows/deploy-dev.yml` — push to `develop`

Triggers the Coolify **dev** application webhook on Hetzner via the `dev` GitHub Environment secrets (`COOLIFY_WEBHOOK_URL`, `COOLIFY_TOKEN`).

#### `.github/workflows/deploy-prod.yml` — push to `main`

Runs the full CI suite first, then triggers the Coolify **prod** application webhook on DigitalOcean via the `prod` GitHub Environment secrets.

### GitHub Environment secrets required

| Secret | Description |
|---|---|
| `COOLIFY_WEBHOOK_URL` | Coolify deploy webhook URL for the app |
| `COOLIFY_TOKEN` | Coolify API token |

| Variable | Description |
|---|---|
| `APP_URL` | Public URL of the deployed app (logged after deploy) |

### Coolify setup

1. In Coolify, create an application pointing at this GitHub repo.
2. Set the Dockerfile as the build source.
3. Mount a persistent volume to `/app/media`.
4. Copy the Coolify API token and the app's deploy webhook URL into the corresponding GitHub Environment secrets.

---

## Models Overview

| Model | Description |
|---|---|
| `Charity` | A registered charity organisation linked to a Django `User` account. |
| `VideoTemplate` | An uploaded base video with an optional overlay spec (JSON) used for template-based sends. |
| `TextTemplate` | A named text body with ElevenLabs voice ID and locale, used to generate TTS voiceovers. Supports `{{donor_name}}`, `{{donation_amount}}`, `{{charity}}`, `{{campaign_name}}` placeholders. |
| `Donor` | A donor record scoped to a charity (unique per `charity + email`). |
| `Campaign` | Links a charity to a campaign type, video template, and text template with configurable gratitude cooldown. |
| `Donation` | A financial donation record linking donor, charity, amount, and campaign type. |
| `VideoSendLog` | Audit log of every video send attempt, including Cloudflare Stream metadata, email provider message ID, and error details. |
