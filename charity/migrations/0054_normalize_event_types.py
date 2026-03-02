"""
Data migration: Normalize all EmailEvent and VideoEvent event_type values to uppercase.

Maps legacy lowercase/mixed-case event types to their canonical uppercase equivalents:
  - EmailEvent: sent→SENT, failed→FAILED, bounced→BOUNCED, delivered→SENT,
                opened→OPEN, clicked→CLICK, unsub→UNSUB
  - VideoEvent: generated→GENERATED, play_started→PLAY,
                25_percent/50_percent/75_percent→PROGRESS, 100_percent→COMPLETE
"""

from django.db import migrations


# Mapping: old_value → new_value
EMAIL_EVENT_MAP = {
    "sent": "SENT",
    "delivered": "SENT",       # delivered is logically the same as SENT
    "failed": "FAILED",
    "bounced": "BOUNCED",
    "opened": "OPEN",
    "clicked": "CLICK",
    "unsub": "UNSUB",
}

VIDEO_EVENT_MAP = {
    "generated": "GENERATED",
    "play_started": "PLAY",
    "25_percent": "PROGRESS",
    "50_percent": "PROGRESS",
    "75_percent": "PROGRESS",
    "100_percent": "COMPLETE",
}


def normalize_event_types(apps, schema_editor):
    EmailEvent = apps.get_model("charity", "EmailEvent")
    VideoEvent = apps.get_model("charity", "VideoEvent")

    for old_val, new_val in EMAIL_EVENT_MAP.items():
        updated = EmailEvent.objects.filter(event_type=old_val).update(event_type=new_val)
        if updated:
            print(f"  EmailEvent: {old_val} → {new_val} ({updated} rows)")

    for old_val, new_val in VIDEO_EVENT_MAP.items():
        updated = VideoEvent.objects.filter(event_type=old_val).update(event_type=new_val)
        if updated:
            print(f"  VideoEvent: {old_val} → {new_val} ({updated} rows)")


def reverse_noop(apps, schema_editor):
    # Irreversible — we cannot recover original mixed-case values
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("charity", "0053_campaign_cf_stream_fields"),
    ]

    operations = [
        migrations.RunPython(normalize_event_types, reverse_noop),
    ]
