from django.core.management.base import BaseCommand
import csv
import sys

from charity.models import ReceivedEmail


class Command(BaseCommand):
    help = 'Export received emails to CSV'

    def add_arguments(self, parser):
        parser.add_argument('--output', '-o', help='Output CSV file path', default=None)
        parser.add_argument('--charity', type=int, help='Charity id to filter', default=None)

    def handle(self, *args, **options):
        qs = ReceivedEmail.objects.all().select_related('charity')
        if options.get('charity'):
            qs = qs.filter(charity_id=options['charity'])

        fields = ['id', 'charity_id', 'charity_name', 'sender', 'recipient', 'subject', 'body', 'received_at']

        out = open(options['output'], 'w', newline='', encoding='utf-8') if options.get('output') else sys.stdout
        writer = csv.writer(out)
        writer.writerow(fields)

        count = 0
        for e in qs.iterator():
            writer.writerow([
                e.id, e.charity.id if e.charity else '', getattr(e.charity, 'client_name', ''),
                e.sender, e.recipient, e.subject, e.body, e.received_at
            ])
            count += 1

        if options.get('output'):
            out.close()
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} received emails to {options["output"]}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} received emails to stdout'))
