from celery import group, shared_task
from django.conf import settings
from django.contrib.auth.models import User

from newsfeed.services import invalidate_feed_cache, push_to_feed_cache_bulk
from users.services import get_follower_user_ids


@shared_task
def fanout_photo_uploaded_chunk_task(follower_ids_chunk: list[int], photo_id: int):
    """Sub-task that executes a safe, limited Redis pipeline for a chunk of followers."""
    push_to_feed_cache_bulk(follower_ids_chunk, photo_id)


@shared_task
def fanout_photo_uploaded_task(user_id: int, photo_id: int):
    """
    Orchestrator task: Fetches followers and spawns chunked sub-tasks
    to avoid blocking the Redis Event Loop with massive pipelines.
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    follower_ids = list(get_follower_user_ids(user))
    chunk_size = settings.FANOUT_PIPELINE_CHUNK_SIZE

    # Split follower_ids into chunks to cap the Redis pipeline size
    chunks = [follower_ids[i : i + chunk_size] for i in range(0, len(follower_ids), chunk_size)]

    # Use Celery Canvas (group) to dispatch all sub-tasks concurrently
    if chunks:
        job = group(fanout_photo_uploaded_chunk_task.s(chunk, photo_id) for chunk in chunks)
        job.apply_async()


@shared_task
def fanout_photo_deleted_task(user_id: int):
    """Asynchronously invalidates feed caches of all followers when a photo is deleted."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    for f_id in get_follower_user_ids(user):
        invalidate_feed_cache(f_id)
