from django.core.management.base import BaseCommand
import csv
import sys

from charity.models import DonationBatch


class Command(BaseCommand):
    help = 'Export donation batches to CSV'

    def add_arguments(self, parser):
        parser.add_argument('--output', '-o', help='Output CSV file path', default=None)
        parser.add_argument('--charity', type=int, help='Charity id to filter', default=None)

    def handle(self, *args, **options):
        qs = DonationBatch.objects.all().select_related('charity', 'campaign')
        if options.get('charity'):
            qs = qs.filter(charity_id=options['charity'])

        fields = [
            'id', 'charity_id', 'charity_name', 'campaign_id', 'campaign_name',
            'batch_number', 'csv_filename', 'media_type', 'created_at',
            'total_records', 'success_count', 'failed_count', 'pending_count', 'upload_type'
        ]

        out = open(options['output'], 'w', newline='', encoding='utf-8') if options.get('output') else sys.stdout
        writer = csv.writer(out)
        writer.writerow(fields)

        count = 0
        for b in qs.iterator():
            writer.writerow([
                b.id, b.charity.id if b.charity else '', b.charity.client_name if b.charity else '',
                b.campaign.id if b.campaign else '', getattr(b.campaign, 'name', ''),
                b.batch_number, b.csv_filename, b.media_type, b.created_at,
                b.total_records, b.success_count, b.failed_count, b.pending_count, b.upload_type
            ])
            count += 1

        if options.get('output'):
            out.close()
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} batches to {options["output"]}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} batches to stdout'))
