from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("charity", "0052_invoiceservice_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="campaign",
            name="cf_stream_video_id",
            field=models.CharField(
                blank=True,
                help_text="Cloudflare Stream video UID (cached after first VDM upload)",
                max_length=255,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="campaign",
            name="cf_stream_video_url",
            field=models.URLField(
                blank=True,
                help_text="Cloudflare Stream hosted player URL (cached after first VDM upload)",
                max_length=512,
                null=True,
            ),
        ),
    ]
