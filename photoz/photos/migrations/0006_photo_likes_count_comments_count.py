from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('photos', '0005_photo_idx_photo_caption_trgm'),
    ]

    operations = [
        # SET lock_timeout before ALTER TABLE.
        # Without it, if any active query holds the table, the DDL waits.
        # While DDL waits, every new query queues behind it -- site goes down.
        # With lock_timeout='2s': if the lock can't be grabbed in 2 seconds,
        # the migration fails fast with no queuing. Just retry.
        migrations.RunSQL("SET lock_timeout = '2s'"),
        migrations.AddField(
            model_name='photo',
            name='likes_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='photo',
            name='comments_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunSQL("SET lock_timeout = 0"),
    ]
