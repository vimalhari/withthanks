from __future__ import annotations

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from charity.analytics_models import CampaignStats, EmailEvent, VideoEvent, WatchSession
from charity.models import Campaign, DonationJob, UnsubscribedUser

FAKE_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

FAKE_IPS = [
    "81.2.69.142",
    "87.116.43.25",
    "5.148.30.11",
    "62.253.12.78",
    "188.212.45.9",
    "91.187.220.34",
    "94.2.31.145",
    "80.229.15.88",
    "176.36.12.5",
    "109.145.24.7",
]


class Command(BaseCommand):
    help = "Seed analytics data (EmailEvent, VideoEvent, WatchSession, CampaignStats) for existing DonationJobs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete existing analytics events before re-seeding",
        )

    def handle(self, *args, **options):
        force = options["force"]

        if force:
            self.stdout.write("Clearing existing analytics data...")
            VideoEvent.objects.all().delete()
            WatchSession.objects.all().delete()
            EmailEvent.objects.all().delete()
            CampaignStats.objects.all().delete()
            UnsubscribedUser.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared all analytics events."))

        if not force and EmailEvent.objects.exists():
            self.stdout.write(
                self.style.NOTICE("EmailEvents already exist. Use --force to re-seed.")
            )
            return

        campaigns = Campaign.objects.prefetch_related("campaign_jobs").all()
        total_jobs = 0
        total_email_events = 0
        total_video_events = 0
        total_watch_sessions = 0

        rng = random.Random(42)  # deterministic seed for reproducibility

        for campaign in campaigns:
            jobs = list(campaign.campaign_jobs.select_related("charity").all())
            if not jobs:
                continue

            self.stdout.write(f"  Seeding campaign: {campaign.name} ({len(jobs)} jobs)")

            # Assign realistic real_views / real_clicks to successful jobs
            jobs_to_update = []
            for job in jobs:
                if job.status == "success" and rng.random() < 0.6:
                    job.real_views = rng.randint(1, 5)
                    job.real_clicks = rng.randint(0, job.real_views)
                else:
                    job.real_views = 0
                    job.real_clicks = 0
                jobs_to_update.append(job)
            DonationJob.objects.bulk_update(jobs_to_update, ["real_views", "real_clicks"])

            email_events: list[EmailEvent] = []
            watch_sessions: list[WatchSession] = []

            for job in jobs:
                base_time = job.created_at if job.created_at else timezone.now()
                ua = rng.choice(FAKE_USER_AGENTS)
                ip = rng.choice(FAKE_IPS)

                # SENT
                sent_time = base_time + timedelta(minutes=rng.randint(1, 30))
                email_events.append(
                    EmailEvent(
                        campaign=campaign,
                        job=job,
                        event_type="SENT",
                        timestamp=sent_time,
                        ip_address=ip,
                        user_agent=ua,
                    )
                )

                # BOUNCED (3% — mutually exclusive with DELIVERED)
                if rng.random() < 0.03:
                    email_events.append(
                        EmailEvent(
                            campaign=campaign,
                            job=job,
                            event_type="BOUNCED",
                            timestamp=sent_time + timedelta(minutes=rng.randint(1, 5)),
                            ip_address=ip,
                            user_agent=ua,
                        )
                    )
                    total_jobs += 1
                    continue  # No further events for bounced

                # DELIVERED
                delivered_time = sent_time + timedelta(minutes=rng.randint(1, 3))
                email_events.append(
                    EmailEvent(
                        campaign=campaign,
                        job=job,
                        event_type="DELIVERED",
                        timestamp=delivered_time,
                        ip_address=ip,
                        user_agent=ua,
                    )
                )

                # OPEN (45% chance)
                if rng.random() < 0.45:
                    open_time = delivered_time + timedelta(hours=rng.uniform(1, 48))
                    email_events.append(
                        EmailEvent(
                            campaign=campaign,
                            job=job,
                            event_type="OPEN",
                            timestamp=open_time,
                            ip_address=ip,
                            user_agent=ua,
                        )
                    )

                    # CLICK (30% of opens)
                    if rng.random() < 0.30:
                        email_events.append(
                            EmailEvent(
                                campaign=campaign,
                                job=job,
                                event_type="CLICK",
                                timestamp=open_time + timedelta(minutes=rng.randint(1, 60)),
                                ip_address=ip,
                                user_agent=ua,
                            )
                        )

                    # UNSUB (2% of opens — EmailEvent.save() rejects for WithThanks campaigns)
                    if rng.random() < 0.02:
                        email_events.append(
                            EmailEvent(
                                campaign=campaign,
                                job=job,
                                event_type="UNSUB",
                                timestamp=open_time + timedelta(minutes=rng.randint(2, 10)),
                                ip_address=ip,
                                user_agent=ua,
                            )
                        )
                        if job.charity:
                            UnsubscribedUser.objects.get_or_create(
                                charity=job.charity,
                                email=job.email,
                                defaults={
                                    "reason": "Unsubscribed via email link",
                                    "unsubscribed_from_job": job,
                                    "ip_address": ip,
                                    "user_agent": ua,
                                },
                            )

                # COMPLAINED (0.5% chance)
                if rng.random() < 0.005:
                    email_events.append(
                        EmailEvent(
                            campaign=campaign,
                            job=job,
                            event_type="COMPLAINED",
                            timestamp=delivered_time + timedelta(hours=rng.uniform(1, 8)),
                            ip_address=ip,
                            user_agent=ua,
                        )
                    )

                # WatchSession for jobs with real_views > 0
                if job.real_views > 0:
                    session = WatchSession(
                        job=job,
                        ip_address=rng.choice(FAKE_IPS),
                        user_agent=rng.choice(FAKE_USER_AGENTS),
                        total_seconds_watched=rng.uniform(30, 180),
                    )
                    watch_sessions.append(session)
                    job._seeded_session = session  # type: ignore[attr-defined]

                total_jobs += 1

            # Bulk-create email events
            created_emails = EmailEvent.objects.bulk_create(email_events, ignore_conflicts=True)
            total_email_events += len(created_emails)

            # Bulk-create watch sessions (UUIDs assigned at instantiation — PKs are available)
            if watch_sessions:
                WatchSession.objects.bulk_create(watch_sessions)
                total_watch_sessions += len(watch_sessions)

            # Video events — reference the already-UUID-assigned session objects
            video_events: list[VideoEvent] = []
            for job in jobs:
                session = getattr(job, "_seeded_session", None)
                if session is None:
                    continue

                rng2 = random.Random(job.pk)
                play_time = timezone.now() - timedelta(days=rng2.randint(1, 30))

                # PLAY
                video_events.append(
                    VideoEvent(
                        session=session,
                        campaign=campaign,
                        job=job,
                        event_type="PLAY",
                        watch_duration=0.0,
                        completion_percentage=0.0,
                        timestamp=play_time,
                    )
                )

                # PROGRESS (70% of plays)
                if rng2.random() < 0.70:
                    video_events.append(
                        VideoEvent(
                            session=session,
                            campaign=campaign,
                            job=job,
                            event_type="PROGRESS",
                            watch_duration=rng2.uniform(30, 90),
                            completion_percentage=rng2.uniform(25, 75),
                            timestamp=play_time + timedelta(seconds=rng2.randint(30, 90)),
                        )
                    )

                # COMPLETE (45% of plays)
                if rng2.random() < 0.45:
                    video_events.append(
                        VideoEvent(
                            session=session,
                            campaign=campaign,
                            job=job,
                            event_type="COMPLETE",
                            watch_duration=rng2.uniform(90, 180),
                            completion_percentage=100.0,
                            timestamp=play_time + timedelta(seconds=rng2.randint(91, 180)),
                        )
                    )

            if video_events:
                created_videos = VideoEvent.objects.bulk_create(video_events)
                total_video_events += len(created_videos)

            # Rebuild CampaignStats from the new events
            stats, _ = CampaignStats.objects.get_or_create(campaign=campaign)
            stats.update_stats()

            self.stdout.write(
                f"    → {len(email_events)} email events | "
                f"{len(watch_sessions)} sessions | "
                f"{len(video_events)} video events | "
                f"stats updated"
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Seeded {total_jobs} jobs across {campaigns.count()} campaigns:\n"
                f"  EmailEvents:    {total_email_events}\n"
                f"  WatchSessions:  {total_watch_sessions}\n"
                f"  VideoEvents:    {total_video_events}"
            )
        )
