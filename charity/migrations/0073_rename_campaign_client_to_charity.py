from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("charity", "0072_rename_client_name_charity_charity_name_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="campaign",
            old_name="client",
            new_name="charity",
        ),
    ]
