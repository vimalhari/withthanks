"""
Add Stripe integration fields to Charity and Invoice models.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("charity", "0054_normalize_event_types"),
    ]

    operations = [
        # Charity: stripe_customer_id
        migrations.AddField(
            model_name="charity",
            name="stripe_customer_id",
            field=models.CharField(
                blank=True,
                help_text="Stripe Customer ID (cus_xxx)",
                max_length=255,
                null=True,
            ),
        ),
        # Invoice: Stripe fields
        migrations.AddField(
            model_name="invoice",
            name="stripe_invoice_id",
            field=models.CharField(
                blank=True,
                help_text="Stripe Invoice ID (in_xxx)",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="stripe_hosted_url",
            field=models.URLField(
                blank=True,
                help_text="Stripe hosted invoice payment page URL",
                max_length=512,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="stripe_pdf_url",
            field=models.URLField(
                blank=True,
                help_text="Stripe-generated PDF URL",
                max_length=512,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="stripe_payment_intent_id",
            field=models.CharField(
                blank=True,
                help_text="Stripe PaymentIntent ID (pi_xxx)",
                max_length=255,
                null=True,
            ),
        ),
        # Update EmailEvent choices (remove backward compat aliases)
        migrations.AlterField(
            model_name="emailevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("SENT", "Sent"),
                    ("FAILED", "Failed"),
                    ("BOUNCED", "Bounced"),
                    ("OPEN", "Open"),
                    ("CLICK", "Click"),
                    ("UNSUB", "Unsubscribe"),
                ],
                max_length=50,
            ),
        ),
        # Update VideoEvent choices (remove backward compat aliases)
        migrations.AlterField(
            model_name="videoevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("GENERATED", "Generated"),
                    ("PLAY", "Play"),
                    ("PROGRESS", "Progress"),
                    ("COMPLETE", "Complete"),
                ],
                max_length=50,
            ),
        ),
    ]
