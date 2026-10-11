from celery import shared_task
from django.contrib.auth.models import User

from newsfeed.services import invalidate_feed_cache
from users.services import get_follower_user_ids


@shared_task
def fanout_photo_deleted_task(user_id: int):
    """Asynchronously invalidates feed caches of all followers when a photo is deleted."""
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    for f_id in get_follower_user_ids(user):
        invalidate_feed_cache(f_id)
