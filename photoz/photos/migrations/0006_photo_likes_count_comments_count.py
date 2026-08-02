from django.db import migrations, models
from django.db.models import Count


def backfill_counts(apps, schema_editor):
    Photo = apps.get_model('photos', 'Photo')
    Like = apps.get_model('photos', 'Like')
    Comment = apps.get_model('photos', 'Comment')

    like_counts = dict(
        Like.objects.values('photo_id').annotate(c=Count('id')).values_list('photo_id', 'c')
    )
    comment_counts = dict(
        Comment.objects.values('photo_id').annotate(c=Count('id')).values_list('photo_id', 'c')
    )

    batch = []
    for photo in Photo.objects.all().iterator(chunk_size=500):
        photo.likes_count = like_counts.get(photo.id, 0)
        photo.comments_count = comment_counts.get(photo.id, 0)
        batch.append(photo)
        if len(batch) == 500:
            Photo.objects.bulk_update(batch, ['likes_count', 'comments_count'])
            batch = []
    if batch:
        Photo.objects.bulk_update(batch, ['likes_count', 'comments_count'])


class Migration(migrations.Migration):

    dependencies = [
        ('photos', '0005_photo_idx_photo_caption_trgm'),
    ]

    operations = [
        # Set lock_timeout before each ALTER TABLE.
        #
        # ALTER TABLE ADD COLUMN takes an ACCESS EXCLUSIVE lock on photos_photo.
        # Without lock_timeout, if any active transaction holds the table,
        # this DDL waits -- and every new query queues behind the DDL lock.
        # With a 2-second lock_timeout: if the lock can't be grabbed in 2s,
        # the migration fails fast (no queuing, no outage). Just retry.
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
        migrations.RunPython(backfill_counts, reverse_code=migrations.RunPython.noop),
    ]
