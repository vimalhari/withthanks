import contextlib
import csv
import sys

from django.core.management.base import BaseCommand

from charity.models import UnsubscribedUser


class Command(BaseCommand):
    help = "Export unsubscribed users to CSV"

    def add_arguments(self, parser):
        parser.add_argument("--output", "-o", help="Output CSV file path", default=None)
        parser.add_argument("--charity", type=int, help="Charity id to filter", default=None)

    def handle(self, *args, **options):
        qs = UnsubscribedUser.objects.all().select_related("charity", "unsubscribed_from_job")
        if options.get("charity"):
            qs = qs.filter(charity_id=options["charity"])

        fields = [
            "id",
            "email",
            "charity_id",
            "charity_name",
            "reason",
            "unsubscribed_from_job_id",
            "ip_address",
            "user_agent",
            "created_at",
        ]

        output_file = options.get("output")
        count = 0
        with (
            open(output_file, "w", newline="", encoding="utf-8")
            if output_file
            else contextlib.nullcontext(sys.stdout)
        ) as out:
            writer = csv.writer(out)
            writer.writerow(fields)

            for u in qs.iterator():
                writer.writerow(
                    [
                        u.id,
                        u.email,
                        u.charity.id if u.charity else "",
                        getattr(u.charity, "client_name", ""),
                        u.reason,
                        u.unsubscribed_from_job.id if u.unsubscribed_from_job else "",
                        u.ip_address,
                        u.user_agent,
                        u.created_at,
                    ]
                )
                count += 1

        if output_file:
            self.stdout.write(self.style.SUCCESS(f"Wrote {count} unsubscribes to {output_file}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Wrote {count} unsubscribes to stdout"))
