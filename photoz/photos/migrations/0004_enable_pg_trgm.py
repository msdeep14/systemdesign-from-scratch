from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("photos", "0003_remove_photo_idx_photo_created_at"),
    ]

    operations = [
        TrigramExtension(),
    ]
