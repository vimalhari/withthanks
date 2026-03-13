from django.core.management.base import BaseCommand

from charity.models import InvoiceService


class Command(BaseCommand):
    help = "Seed the database with global services for billing"

    def handle(self, *args, **options):
        services = [
            # SET UP & MANAGEMENT
            (
                "Email sign off",
                "setup",
                50.00,
                "Standard email signature and sign-off processing.",
            ),
            (
                "Additional programming",
                "setup",
                120.00,
                "Custom logic for campaign routing or data mapping.",
            ),
            (
                "Reformatting of data & clean up",
                "setup",
                60.00,
                "Processing Excel/CSV files for video generation.",
            ),
            (
                "Additional donate page",
                "setup",
                50.00,
                "Hosting and styling of supplementary landing page.",
            ),
            # VIDEO PRODUCTION
            (
                "Personalisation & voiceover amends",
                "production",
                55.00,
                "Custom voiceover updates and donor name matching.",
            ),
            ("Text amends", "production", 30.00, "Minor text changes in overlays or subtitles."),
            ("RE-proof", "production", 30.00, "Regenerating proof copy after changes."),
            (
                "Charity supplied audio clean up",
                "production",
                65.00,
                "Equalization and noise reduction for charity audio.",
            ),
            (
                "Video Direct Mail",
                "production",
                575.00,
                "Full VDM campaign: outreach, stitches, audio, VO, and CTA.",
            ),
            (
                "Charity supplied video/audio (VDM)",
                "production",
                450.00,
                "VDM execution using charity-provided media.",
            ),
            # VOLUME PRICING (production tier)
            ("Volume: 0-99 videos", "production", 0.00, "Base volume tier."),
            ("Volume: 101-300 videos", "production", 0.00, "Mid volume tier."),
            ("Volume: 301-500 videos", "production", 0.00, "Higher volume tier."),
            ("Volume: 501-1000 videos", "production", 0.00, "Enterprise volume tier."),
            ("Volume: 1001-3000 videos", "production", 0.00, "Large scale tier."),
            ("Volume: 3000+ videos (POA)", "production", 0.00, "Custom volume pricing."),
            # GRATITUDE CARDS
            ("Gratitude E Card", "gratitude", 250.00, "Motion short clip with donor name, no CTA."),
            # OTHER
            ("Receipt CSV file", "other", 10.00, "Generating detailed receipt log per file."),
            ("Analytics report", "other", 30.00, "Custom periodic analytics delivery."),
            (
                "Bounce back error log",
                "other",
                30.00,
                "Detailed email delivery failure report.",
            ),
        ]

        for name, category, price, desc in services:
            _, created = InvoiceService.objects.update_or_create(
                name=name,
                defaults={
                    "category": category,
                    "unit_price": price,
                    "description": desc,
                    "is_active": True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created service: {name}"))
            else:
                self.stdout.write(f"Updated service: {name}")

        self.stdout.write(self.style.SUCCESS("Successfully seeded global services!"))
