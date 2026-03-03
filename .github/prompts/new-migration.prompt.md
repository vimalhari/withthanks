---
description: "Generate a Django data migration for WithThanks"
---

# New Data Migration

Create a Django data migration for the WithThanks project.

## Requirements
- Use `RunPython` with both forward and reverse functions.
- Always scope data changes to individual charities where applicable.
- Use `apps.get_model()` to reference models (not direct imports).
- Test both forward and reverse migration paths.

## Template
```python
from django.db import migrations


def forwards(apps, schema_editor):
    """${1:Description of what this migration does}."""
    Model = apps.get_model("charity", "${2:ModelName}")

    # Perform data migration
    for obj in Model.objects.all():
        # Update logic here
        obj.save(update_fields=["${3:field_name}"])


def backwards(apps, schema_editor):
    """Reverse the data migration."""
    Model = apps.get_model("charity", "${2}")

    # Reverse logic here
    for obj in Model.objects.all():
        obj.save(update_fields=["${3}"])


class Migration(migrations.Migration):
    dependencies = [
        ("charity", "${4:previous_migration}"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
```

## After Creating
1. Run `uv run python manage.py migrate` to apply.
2. Verify data state in Django shell: `uv run python manage.py shell`.
