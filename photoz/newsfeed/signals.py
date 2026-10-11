from django.core.cache import cache
from django.dispatch import receiver

from communities.signals import invitation_accepted
from newsfeed.services import (
    CELEBRITY_FOLLOWER_THRESHOLD,
    invalidate_feed_cache,
)
from newsfeed.tasks import fanout_photo_deleted_task
from photos.signals import photo_deleted


@receiver(photo_deleted)
def _handle_photo_deleted(sender, user, **kwargs):
    follower_count = getattr(user, "profile", None)
    follower_count = follower_count.follower_count if follower_count else 0

    invalidate_feed_cache(user.id)

    if follower_count > CELEBRITY_FOLLOWER_THRESHOLD:
        return

    fanout_photo_deleted_task.delay(user.id)


@receiver(invitation_accepted)
def _handle_invitation_accepted(sender, user, **kwargs):
    cache.delete(f"feed:{user.id}")
