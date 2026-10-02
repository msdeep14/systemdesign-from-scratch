from celery import shared_task
from django.contrib.auth.models import User

from newsfeed.services import invalidate_feed_cache, push_to_feed_cache_bulk
from users.services import get_follower_user_ids


@shared_task
def fanout_photo_uploaded_task(user_id: int, photo_id: int):
    """Asynchronously pushes a newly uploaded photo to all followers'
    feeds using Redis pipelining."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    follower_ids = get_follower_user_ids(user)
    push_to_feed_cache_bulk(follower_ids, photo_id)


@shared_task
def fanout_photo_deleted_task(user_id: int):
    """Asynchronously invalidates feed caches of all followers when a photo is deleted."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    for f_id in get_follower_user_ids(user):
        invalidate_feed_cache(f_id)
