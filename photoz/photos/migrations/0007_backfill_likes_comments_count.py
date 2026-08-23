from django.db import migrations, transaction
from django.db.models import Count


def backfill_counts(apps, schema_editor):
    Photo = apps.get_model("photos", "Photo")
    Like = apps.get_model("photos", "Like")
    Comment = apps.get_model("photos", "Comment")

    like_counts = dict(
        Like.objects.values("photo_id").annotate(c=Count("id")).values_list("photo_id", "c")
    )
    comment_counts = dict(
        Comment.objects.values("photo_id").annotate(c=Count("id")).values_list("photo_id", "c")
    )

    # Use ID-based pagination instead of iterator(chunk_size=...).
    #
    # iterator(chunk_size=N) opens a named PostgreSQL server-side cursor.
    # When transaction.atomic() commits inside the loop, the transaction ends
    # and Postgres invalidates the cursor -- causing InvalidCursorName errors
    # when the next fetchmany() is called (especially through PgBouncer).
    #
    # ID-based pagination issues a plain SELECT per batch with no named cursor,
    # so commits inside the loop are safe.
    last_id = 0
    while True:
        batch_ids = list(
            Photo.objects.filter(id__gt=last_id).order_by("id").values_list("id", flat=True)[:500]
        )
        if not batch_ids:
            break
        batch = list(Photo.objects.filter(id__in=batch_ids))
        for photo in batch:
            photo.likes_count = like_counts.get(photo.id, 0)
            photo.comments_count = comment_counts.get(photo.id, 0)
        with transaction.atomic():
            Photo.objects.bulk_update(batch, ["likes_count", "comments_count"])
        last_id = batch_ids[-1]


class Migration(migrations.Migration):
    # atomic=False so Django does not wrap the entire migration in one transaction.
    # Without this, all 200 batch updates run in a single open transaction that
    # holds the DB connection for 60-90 seconds, starving other Gunicorn workers
    # (max_connections=20 on this Postgres instance).
    # With atomic=False, each bulk_update batch commits independently.
    atomic = False

    dependencies = [
        ("photos", "0006_photo_likes_count_comments_count"),
    ]

    operations = [
        migrations.RunPython(backfill_counts, reverse_code=migrations.RunPython.noop),
    ]
