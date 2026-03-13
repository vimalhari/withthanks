"""
Management command: seed_data
Creates a realistic demo dataset for development, staging, and first-run production setup.

Usage:
    python manage.py seed_data                  # Full demo seed (idempotent)
    python manage.py seed_data --no-invoices    # Skip invoice creation
    python manage.py seed_data --flush          # WIPE and re-seed (dev only)
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from charity.models import (
    Campaign,
    Charity,
    CharityMember,
    DonationBatch,
    DonationJob,
    Invoice,
    InvoiceLineItem,
    InvoiceService,
)

# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

CHARITIES = [
    {
        "slug": "green_earth",
        "client_name": "Green Earth Foundation",
        "organization_name": "Green Earth Foundation Ltd",
        "contact_email": "hello@greenearthfoundation.example.com",
        "billing_email": "billing@greenearthfoundation.example.com",
        "billing_address": "1 Eco Park, London, EC1A 1BB",
        "contact_phone": "+44 20 7946 0001",
        "company_number": "CE123456",
        "address_line_1": "1 Eco Park",
        "county": "London",
        "postcode": "EC1A 1BB",
    },
    {
        "slug": "bright_futures",
        "client_name": "Bright Futures Trust",
        "organization_name": "Bright Futures Charitable Trust",
        "contact_email": "info@brightfutures.example.com",
        "billing_email": "accounts@brightfutures.example.com",
        "billing_address": "22 Hope Street, Manchester, M1 1AD",
        "contact_phone": "+44 161 123 4567",
        "company_number": "BF654321",
        "address_line_1": "22 Hope Street",
        "county": "Greater Manchester",
        "postcode": "M1 1AD",
    },
]

# Users per charity: (username, email, password, role, is_superuser)
USERS = [
    # Global superuser
    ("admin", "admin@withthanks.example.com", "changeme123!", None, True),
    # Green Earth staff
    ("green_admin", "green.admin@greenearthfoundation.example.com", "changeme123!", "Admin", False),
    (
        "green_member",
        "green.member@greenearthfoundation.example.com",
        "changeme123!",
        "Member",
        False,
    ),
    (
        "green_viewer",
        "green.viewer@greenearthfoundation.example.com",
        "changeme123!",
        "Viewer",
        False,
    ),
    # Bright Futures staff
    ("bf_admin", "bf.admin@brightfutures.example.com", "changeme123!", "Admin", False),
    ("bf_member", "bf.member@brightfutures.example.com", "changeme123!", "Member", False),
]

# Campaigns per charity slug
CAMPAIGNS: dict[str, list[dict]] = {
    "green_earth": [
        {
            "name": "Spring Campaign 2025",
            "campaign_code": "GE-2025-SPR",
            "campaign_mode": "THANK_YOU_PERSONALIZED",
            "campaign_start": date(2025, 3, 1),
            "campaign_end": date(2025, 5, 31),
            "status": "closed",
            "description": "Spring fundraising campaign targeting regular donors.",
        },
        {
            "name": "Summer Giving 2025",
            "campaign_code": "GE-2025-SUM",
            "campaign_mode": "THANK_YOU_PERSONALIZED",
            "campaign_start": date(2025, 6, 1),
            "campaign_end": date(2025, 8, 31),
            "status": "active",
            "description": "Summer campaign with video personalisation.",
        },
    ],
    "bright_futures": [
        {
            "name": "Education Fund 2025",
            "campaign_code": "BF-2025-EDU",
            "campaign_mode": "THANK_YOU_PERSONALIZED",
            "campaign_start": date(2025, 1, 15),
            "campaign_end": date(2025, 6, 30),
            "status": "active",
            "description": "Annual education fund campaign.",
        },
        {
            "name": "VDM Outreach Q1",
            "campaign_code": "BF-2025-VDM",
            "campaign_mode": "VDM",
            "campaign_start": date(2025, 1, 1),
            "campaign_end": date(2025, 3, 31),
            "status": "closed",
            "description": "Direct mail video campaign Q1.",
        },
    ],
}

# Sample donors for generating jobs
_DONORS = [
    ("Alice Johnson", "alice.johnson@example.com", "100.00"),
    ("Bob Williams", "bob.williams@example.com", "50.00"),
    ("Carol Smith", "carol.smith@example.com", "250.00"),
    ("David Brown", "david.brown@example.com", "75.00"),
    ("Emma Davis", "emma.davis@example.com", "150.00"),
    ("Frank Wilson", "frank.wilson@example.com", "200.00"),
    ("Grace Taylor", "grace.taylor@example.com", "30.00"),
    ("Henry Thomas", "henry.thomas@example.com", "500.00"),
    ("Irene Moore", "irene.moore@example.com", "20.00"),
    ("James Martin", "james.martin@example.com", "120.00"),
    ("Karen White", "karen.white@example.com", "85.00"),
    ("Liam Harris", "liam.harris@example.com", "300.00"),
]


class Command(BaseCommand):
    help = (
        "Seed the database with demo data: superuser, charities, users, campaigns, "
        "donation batches, jobs, and invoices. Idempotent by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            default=False,
            help=(
                "DELETE all charity/user/invoice data and re-seed from scratch. "
                "DANGEROUS — dev/staging only."
            ),
        )
        parser.add_argument(
            "--no-invoices",
            action="store_true",
            default=False,
            help="Skip creating sample invoices.",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self._flush()

        self._print_header("1. Seeding invoice services catalogue")
        call_command("seed_services", verbosity=0)
        self.stdout.write(self.style.SUCCESS("  ✓ Invoice services catalogue up to date"))

        self._print_header("2. Creating superuser")
        superuser = self._create_user("admin", "admin@withthanks.example.com", "changeme123!", True)

        self._print_header("3. Creating charities and users")
        charity_map: dict[str, Charity] = {}
        for charity_data in CHARITIES:
            slug = charity_data.pop("slug")
            charity = self._create_charity(charity_data)
            charity_map[slug] = charity
            charity_data["slug"] = slug  # restore for idempotency

        # Create users and link to charities
        user_map: dict[str, User] = {"admin": superuser}
        charity_slug_map = {
            "green_admin": "green_earth",
            "green_member": "green_earth",
            "green_viewer": "green_earth",
            "bf_admin": "bright_futures",
            "bf_member": "bright_futures",
        }
        for username, email, password, role, is_super in USERS:
            if username == "admin":
                continue
            user = self._create_user(username, email, password, is_super)
            user_map[username] = user
            if role:
                charity_slug = charity_slug_map[username]
                self._create_membership(charity_map[charity_slug], user, role)

        self._print_header("4. Creating campaigns")
        campaign_map: dict[str, list[Campaign]] = {}
        for slug, campaigns_data in CAMPAIGNS.items():
            charity = charity_map[slug]
            campaign_map[slug] = []
            for cd in campaigns_data:
                campaign = self._create_campaign(charity, cd)
                campaign_map[slug].append(campaign)

        self._print_header("5. Creating donation batches and jobs")
        batch_map: dict[str, list[DonationBatch]] = {}
        for slug, campaigns in campaign_map.items():
            charity = charity_map[slug]
            batch_map[slug] = []
            for i, campaign in enumerate(campaigns):
                batch = self._create_batch(charity, campaign, i + 1)
                batch_map[slug].append(batch)
                self._create_jobs(charity, campaign, batch)

        if options["no_invoices"]:
            self.stdout.write(self.style.WARNING("  Skipping invoice creation (--no-invoices)"))
        else:
            self._print_header("6. Creating sample invoices")
            self._create_invoices(charity_map, batch_map)

        self._print_summary()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _print_header(self, text: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))

    def _flush(self) -> None:
        import django.conf

        if not django.conf.settings.DEBUG:
            raise CommandError(
                "Refusing to flush in production (DEBUG is False). "
                "Use --flush only on development/staging environments."
            )
        self.stdout.write(self.style.WARNING("  Flushing demo data..."))
        DonationJob.objects.all().delete()
        DonationBatch.objects.all().delete()
        InvoiceLineItem.objects.all().delete()
        Invoice.objects.all().delete()
        Campaign.objects.all().delete()
        CharityMember.objects.all().delete()
        Charity.objects.all().delete()
        User.objects.filter(is_superuser=False).exclude(username="admin").delete()
        self.stdout.write(self.style.WARNING("  Flush complete."))

    def _create_user(self, username: str, email: str, password: str, is_super: bool) -> User:
        user, created = User.objects.get_or_create(username=username)
        user.email = email
        user.set_password(password)
        user.is_staff = is_super
        user.is_superuser = is_super
        user.save()
        label = "superuser" if is_super else "user"
        verb = "Created" if created else "Updated"
        self.stdout.write(f"  {verb} {label}: {username}")
        return user

    def _create_charity(self, data: dict) -> Charity:
        charity, created = Charity.objects.get_or_create(
            client_name=data["client_name"],
            defaults={k: v for k, v in data.items() if k != "client_name"},
        )
        if not created:
            for field, value in data.items():
                if field != "client_name":
                    setattr(charity, field, value)
            charity.save()
        verb = "Created" if created else "Updated"
        self.stdout.write(f"  {verb} charity: {charity.client_name}")
        return charity

    def _create_membership(self, charity: Charity, user: User, role: str) -> None:
        _, created = CharityMember.objects.get_or_create(
            charity=charity,
            user=user,
            defaults={"role": role, "status": "ACTIVE"},
        )
        if created:
            self.stdout.write(f"    → Linked {user.username} to {charity.client_name} as {role}")

    def _create_campaign(self, charity: Charity, data: dict) -> Campaign:
        existing = Campaign.objects.filter(
            client=charity,
            campaign_code=data["campaign_code"],
        ).order_by("created_at", "id")
        campaign = existing.first()
        created = campaign is None

        if campaign is None:
            campaign = Campaign.objects.create(
                client=charity,
                campaign_code=data["campaign_code"],
                name=data["name"],
                campaign_mode=data["campaign_mode"],
                campaign_start=data["campaign_start"],
                campaign_end=data["campaign_end"],
                status=data["status"],
                description=data.get("description", ""),
            )
        else:
            duplicate_count = max(existing.count() - 1, 0)
            if duplicate_count:
                self.stdout.write(
                    self.style.WARNING(
                        "  Found duplicate campaigns for code "
                        f"'{data['campaign_code']}' on {charity.client_name}; "
                        f"using earliest record ({campaign.id})."
                    )
                )
            campaign.name = data["name"]
            campaign.campaign_mode = data["campaign_mode"]
            campaign.campaign_start = data["campaign_start"]
            campaign.campaign_end = data["campaign_end"]
            campaign.status = data["status"]
            campaign.description = data.get("description", "")
            campaign.save()

        verb = "Created" if created else "Found"
        self.stdout.write(f"  {verb} campaign: {campaign.name}")
        return campaign

    def _create_batch(
        self, charity: Charity, campaign: Campaign, batch_number: int
    ) -> DonationBatch:
        existing = DonationBatch.objects.filter(
            charity=charity,
            campaign=campaign,
            batch_number=batch_number,
        ).order_by("id")
        batch = existing.first()
        created = batch is None

        if batch is None:
            batch = DonationBatch.objects.create(
                charity=charity,
                campaign=campaign,
                batch_number=batch_number,
                campaign_name=campaign.name,
                status=DonationBatch.BatchStatus.COMPLETED,
                csv_filename=f"demo_batch_{batch_number}.csv",
            )
        else:
            duplicate_count = max(existing.count() - 1, 0)
            if duplicate_count:
                self.stdout.write(
                    self.style.WARNING(
                        "    Found duplicate batches for campaign "
                        f"'{campaign.name}' batch #{batch_number}; using earliest record ({batch.id})."
                    )
                )
            batch.campaign_name = campaign.name
            batch.status = DonationBatch.BatchStatus.COMPLETED
            batch.csv_filename = f"demo_batch_{batch_number}.csv"
            batch.save()

        verb = "Created" if created else "Found"
        self.stdout.write(f"  {verb} batch #{batch_number} for '{campaign.name}'")
        return batch

    def _create_jobs(self, charity: Charity, campaign: Campaign, batch: DonationBatch) -> None:
        sample_donors = random.sample(_DONORS, k=min(6, len(_DONORS)))
        created_count = 0
        for donor_name, email, amount in sample_donors:
            # Use a charity-unique email per batch to avoid unique_together collisions
            unique_email = f"{batch.id}.{email}"
            _, created = DonationJob.objects.get_or_create(
                donation_batch=batch,
                email=unique_email,
                defaults={
                    "donor_name": donor_name,
                    "donation_amount": amount,
                    "charity": charity,
                    "campaign": campaign,
                    "status": random.choice(["success", "success", "success", "failed"]),
                    "real_views": random.randint(0, 5),
                    "real_clicks": random.randint(0, 2),
                    "completed_at": timezone.now() - timedelta(days=random.randint(1, 30)),
                },
            )
            if created:
                created_count += 1
        self.stdout.write(f"    → Created {created_count} donation jobs")

    def _create_invoices(
        self,
        charity_map: dict[str, Charity],
        batch_map: dict[str, list[DonationBatch]],
    ) -> None:
        today = date.today()
        invoice_configs = [
            {
                "slug": "green_earth",
                "batch_idx": 0,
                "invoice_number": "INV-SEED-GE-001",
                "status": "Paid",
                "issue_date": today - timedelta(days=60),
                "due_date": today - timedelta(days=30),
                "amount": "975.00",
                "services": [
                    ("Email sign off", "setup", 1, 50.00),
                    ("Personalisation & voiceover amends", "production", 1, 55.00),
                    ("Volume: 101-300 videos", "production", 150, 5.80),
                ],
            },
            {
                "slug": "green_earth",
                "batch_idx": 1,
                "invoice_number": "INV-SEED-GE-002",
                "status": "Sent",
                "issue_date": today - timedelta(days=10),
                "due_date": today + timedelta(days=20),
                "amount": "870.00",
                "services": [
                    ("Email sign off", "setup", 1, 50.00),
                    ("Volume: 101-300 videos", "production", 120, 6.83),
                ],
            },
            {
                "slug": "bright_futures",
                "batch_idx": 0,
                "invoice_number": "INV-SEED-BF-001",
                "status": "Paid",
                "issue_date": today - timedelta(days=90),
                "due_date": today - timedelta(days=60),
                "amount": "1150.00",
                "services": [
                    ("Email sign off", "setup", 1, 50.00),
                    ("Reformatting of data & clean up", "setup", 1, 60.00),
                    ("Volume: 101-300 videos", "production", 200, 5.20),
                ],
            },
            {
                "slug": "bright_futures",
                "batch_idx": 1,
                "invoice_number": "INV-SEED-BF-002",
                "status": "Draft",
                "issue_date": today - timedelta(days=5),
                "due_date": today + timedelta(days=25),
                "amount": "1025.00",
                "services": [
                    ("Video Direct Mail", "production", 1, 575.00),
                    ("Client supplied audio clean up", "production", 1, 65.00),
                    ("Email sign off", "setup", 1, 50.00),
                    ("Analytics report", "other", 1, 30.00),
                ],
            },
        ]

        for cfg in invoice_configs:
            charity = charity_map[cfg["slug"]]
            batches = batch_map[cfg["slug"]]
            batch = batches[cfg["batch_idx"]] if batches else None

            invoice, created = Invoice.objects.get_or_create(
                invoice_number=cfg["invoice_number"],
                defaults={
                    "charity": charity,
                    "campaign": batch.campaign if batch else None,
                    "amount": cfg["amount"],
                    "status": cfg["status"],
                    "issue_date": cfg["issue_date"],
                    "due_date": cfg["due_date"],
                    "billing_email": charity.billing_email or charity.contact_email,
                    "billing_address": charity.billing_address or "",
                    "total_batches": 1,
                    "total_videos": batch.total_records if batch else 0,
                },
            )

            if created:
                # Link line items
                for svc_name, _cat, qty, price in cfg["services"]:
                    service = InvoiceService.objects.filter(name=svc_name).first()
                    InvoiceLineItem.objects.create(
                        invoice=invoice,
                        service=service,
                        description=svc_name,
                        quantity=qty,
                        unit_price=price,
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Created invoice {invoice.invoice_number} ({cfg['status']})"
                    )
                )
            else:
                self.stdout.write(f"  Found invoice {invoice.invoice_number}")

    def _print_summary(self) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("  Seed data complete!"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write("")
        self.stdout.write("  Demo logins (password: changeme123!):")
        self.stdout.write("    admin         — superuser (all charities)")
        self.stdout.write("    green_admin   — Green Earth Foundation Admin")
        self.stdout.write("    green_member  — Green Earth Foundation Member")
        self.stdout.write("    green_viewer  — Green Earth Foundation Viewer")
        self.stdout.write("    bf_admin      — Bright Futures Trust Admin")
        self.stdout.write("    bf_member     — Bright Futures Trust Member")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING("  ⚠  Change all passwords before deploying to production!")
        )
        self.stdout.write("")
