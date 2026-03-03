from django.core.management.base import BaseCommand

from charity.models import InvoiceService


class Command(BaseCommand):
    help = "Seed the database with global services for billing"

    def handle(self, *args, **options):
        services = [
            # ADDITIONAL COSTS
            (
                "Email sign off",
                "ADDITIONAL",
                50.00,
                "Standard email signature and sign-off processing.",
            ),
            (
                "Personalisation & voiceover amends",
                "ADDITIONAL",
                55.00,
                "Custom voiceover updates and donor name matching.",
            ),
            ("Text amends", "ADDITIONAL", 30.00, "Minor text changes in overlays or subtitles."),
            ("RE-proof", "ADDITIONAL", 30.00, "Regenerating proof copy after changes."),
            (
                "Additional programming",
                "ADDITIONAL",
                120.00,
                "Custom logic for campaign routing or data mapping.",
            ),
            (
                "Reformatting of data & clean up",
                "ADDITIONAL",
                60.00,
                "Processing Excel/CSV files for video generation.",
            ),
            (
                "Client supplied audio clean up",
                "ADDITIONAL",
                65.00,
                "Equalization and noise reduction for client audio.",
            ),
            ("Receipt CSV file", "ADDITIONAL", 10.00, "Generating detailed receipt log per file."),
            ("Analytics report", "ADDITIONAL", 30.00, "Custom periodic analytics delivery."),
            (
                "Bounce back error log",
                "ADDITIONAL",
                30.00,
                "Detailed email delivery failure report.",
            ),
            (
                "Additional donate page",
                "ADDITIONAL",
                50.00,
                "Hosting and styling of supplementary landing page.",
            ),
            # VDM
            (
                "Video Direct Mail",
                "VDM",
                575.00,
                "Full VDM campaign: outreach, stitches, audio, VO, and CTA.",
            ),
            (
                "Client supplied video/audio (VDM)",
                "VDM",
                450.00,
                "VDM execution using client-provided media.",
            ),
            # GRATITUDE
            ("Gratitude E Card", "GRATITUDE", 250.00, "Motion short clip with donor name, no CTA."),
            # VOLUME PRICING
            ("Volume: 0-99 videos", "VOLUME", 0.00, "Base volume tier."),
            ("Volume: 101-300 videos", "VOLUME", 0.00, "Mid volume tier."),
            ("Volume: 301-500 videos", "VOLUME", 0.00, "Higher volume tier."),
            ("Volume: 501-1000 videos", "VOLUME", 0.00, "Enterprise volume tier."),
            ("Volume: 1001-3000 videos", "VOLUME", 0.00, "Large scale tier."),
            ("Volume: 3000+ videos (POA)", "VOLUME", 0.00, "Custom volume pricing."),
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
