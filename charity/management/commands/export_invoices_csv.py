from django.core.management.base import BaseCommand
import csv
import sys

from charity.models import Invoice


class Command(BaseCommand):
    help = 'Export invoices to CSV'

    def add_arguments(self, parser):
        parser.add_argument('--output', '-o', help='Output CSV file path', default=None)
        parser.add_argument('--charity', type=int, help='Charity id to filter', default=None)

    def handle(self, *args, **options):
        qs = Invoice.objects.all().select_related('charity')
        if options.get('charity'):
            qs = qs.filter(charity_id=options['charity'])

        fields = [
            'id', 'invoice_number', 'charity_id', 'charity_name', 'amount', 'status',
            'issue_date', 'due_date', 'subtotal', 'tax_amount', 'discount_amount',
            'total_batches', 'total_videos', 'total_views', 'total_clicks', 'total_unsubscribes',
            'period_start', 'period_end', 'created_at'
        ]

        out = open(options['output'], 'w', newline='', encoding='utf-8') if options.get('output') else sys.stdout
        writer = csv.writer(out)
        writer.writerow(fields)

        count = 0
        for inv in qs.iterator():
            writer.writerow([
                inv.id, inv.invoice_number, inv.charity.id if inv.charity else '', getattr(inv.charity, 'client_name', ''),
                inv.amount, inv.status, inv.issue_date, inv.due_date, inv.subtotal, inv.tax_amount, inv.discount_amount,
                inv.total_batches, inv.total_videos, inv.total_views, inv.total_clicks, inv.total_unsubscribes,
                inv.period_start, inv.period_end, inv.created_at
            ])
            count += 1

        if options.get('output'):
            out.close()
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} invoices to {options["output"]}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Wrote {count} invoices to stdout'))
