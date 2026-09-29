from celery import shared_task
from django.db import transaction

from photos.models import Photo
from photos.services import redis_client


@shared_task
def flush_like_counts_task():
    """
    Flushes the exact like counts from Redis (Full Count Strategy) into the PostgreSQL database.
    This runs periodically via Celery Beat.
    """
    pending_photos = redis_client.smembers("photos_with_pending_like_counts")
    if not pending_photos:
        return 0

    updates_count = 0
    # Process in batches to avoid huge transactions if there are many photos
    pending_photos_list = list(pending_photos)
    batch_size = 1000

    for i in range(0, len(pending_photos_list), batch_size):
        batch = pending_photos_list[i : i + batch_size]
        with transaction.atomic():
            for photo_id_str in batch:
                photo_id = int(photo_id_str)
                key = f"photo:{photo_id}:likes_count"

                # Get the absolute count from Redis
                count = redis_client.get(key)

                if count is not None:
                    count_val = int(count)
                    Photo.objects.filter(id=photo_id).update(likes_count=count_val)
                    updates_count += 1

                # Remove from pending set. If new likes happen after get() but before srem(),
                # the next like will add it back to the set.
                redis_client.srem("photos_with_pending_like_counts", photo_id_str)

    return updates_count
