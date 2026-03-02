from django.core.management.base import BaseCommand
import csv
import sys

from charity.models import DonationJob


class Command(BaseCommand):
    help = 'Export donation jobs to CSV'

    def add_arguments(self, parser):
        parser.add_argument('--output', '-o', help='Output CSV file path', default=None)
        parser.add_argument('--charity', type=int, help='Charity id to filter', default=None)
        parser.add_argument('--since', help='Start date YYYY-MM-DD', default=None)
        parser.add_argument('--until', help='End date YYYY-MM-DD', default=None)

    def handle(self, *args, **options):
        qs = DonationJob.objects.all().select_related('charity', 'campaign', 'donation_batch')
        if options.get('charity'):
            qs = qs.filter(charity_id=options['charity'])
        if options.get('since'):
            qs = qs.filter(created_at__gte=options['since'])
        if options.get('until'):
            qs = qs.filter(created_at__lte=options['until'])

        fields = [
            'id', 'donor_name', 'email', 'donation_amount', 'status',
            'charity_id', 'charity_name', 'campaign_id', 'campaign_name',
            'donation_batch_id', 'generation_time', 'created_at', 'completed_at',
            'video_path', 'video_url', 'error_message', 'real_views', 'fake_views',
            'real_clicks', 'fake_clicks'
        ]

        out = open(options['output'], 'w', newline='', encoding='utf-8') if options.get('output') else sys.stdout
        writer = csv.writer(out)
        writer.writerow(fields)

        count = 0
        for j in qs.iterator():
            writer.writerow([
                j.id, j.donor_name, j.email, j.donation_amount, j.status,
                j.charity.id if j.charity else '', j.charity.client_name if j.charity else '',
                j.campaign.id if j.campaign else '', getattr(j.campaign, 'name', ''),
                j.donation_batch.id if j.donation_batch else '', j.generation_time, j.created_at, j.completed_at,
                j.video_path, j.video_url, j.error_message, j.real_views, j.fake_views,
                j.real_clicks, j.fake_clicks
            ])
            count += 1

        if options.get('output'):
            out.close()
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} jobs to {options["output"]}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} jobs to stdout'))
