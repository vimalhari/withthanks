from django.db import migrations

def backfill_campaign_videos(apps, schema_editor):
    Campaign = apps.get_model('charity', 'Campaign')
    
    # Iterate over all campaigns
    for campaign in Campaign.objects.all():
        client = campaign.client
        changed = False
        
        # 1. Backfill Charity Video (VDM Appeal)
        # Use Client's default_template_video if available
        if not campaign.charity_video and client.default_template_video:
            campaign.charity_video = client.default_template_video
            changed = True
            
        # 2. Backfill Gratitude Video (WithThanks Appeal)
        # Use Client's gratitude_card (if it's a video) or default_template_video as fallback?
        # User requirement: "Each Campaign has its own unique Gratitude Video"
        # Logic: If client has a gratitude_card, assume it's the video/image intended.
        # Note: gratitude_card might be an image, but the field is FileField.
        if not campaign.gratitude_video and client.gratitude_card:
            campaign.gratitude_video = client.gratitude_card
            changed = True
            
        if changed:
            campaign.save()

class Migration(migrations.Migration):

    dependencies = [
        ('charity', '0035_campaign_charity_video_campaign_gratitude_video'),
    ]

    operations = [
        migrations.RunPython(backfill_campaign_videos),
    ]
