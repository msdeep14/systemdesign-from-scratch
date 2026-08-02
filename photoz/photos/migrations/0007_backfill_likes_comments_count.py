from django.db import migrations, transaction
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
            # Commit each batch in its own transaction.
            # This keeps individual transactions short (500 rows each), so
            # Postgres connection slots are not held for the full backfill duration.
            with transaction.atomic():
                Photo.objects.bulk_update(batch, ['likes_count', 'comments_count'])
            batch = []
    if batch:
        with transaction.atomic():
            Photo.objects.bulk_update(batch, ['likes_count', 'comments_count'])


class Migration(migrations.Migration):
    # atomic=False so Django does not wrap the entire migration in one transaction.
    # Without this, all 200 batch updates run in a single open transaction that
    # holds the DB connection for 60-90 seconds, starving other Gunicorn workers
    # (max_connections=20 on this Postgres instance).
    # With atomic=False, each bulk_update batch commits independently.
    atomic = False

    dependencies = [
        ('photos', '0006_photo_likes_count_comments_count'),
    ]

    operations = [
        migrations.RunPython(backfill_counts, reverse_code=migrations.RunPython.noop),
    ]
