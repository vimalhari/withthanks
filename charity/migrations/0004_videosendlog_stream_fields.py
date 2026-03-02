# Generated manually — adds Cloudflare Stream fields to VideoSendLog

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("charity", "0003_campaign_donor_donation_videosendlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="videosendlog",
            name="stream_video_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="videosendlog",
            name="stream_playback_url",
            field=models.URLField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="videosendlog",
            name="stream_thumbnail_url",
            field=models.URLField(blank=True, max_length=512),
        ),
    ]
