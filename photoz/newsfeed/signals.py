from django.core.cache import cache
from django.dispatch import receiver

from communities.signals import invitation_accepted
from newsfeed.services import (
    CELEBRITY_FOLLOWER_THRESHOLD,
    invalidate_feed_cache,
    push_to_feed_cache,
)
from photos.signals import photo_deleted, photo_uploaded
from users.services import get_follower_user_ids


@receiver(photo_uploaded)
def _handle_photo_uploaded(sender, photo, **kwargs):
    follower_count = getattr(photo.user, "profile", None)
    follower_count = follower_count.follower_count if follower_count else 0

    # Always push to uploader's own feed
    push_to_feed_cache(photo.user.id, photo.id)

    if follower_count > CELEBRITY_FOLLOWER_THRESHOLD:
        # Celebrity: skip fan-out. Followers will pull this photo at read time.
        return

    # Regular user: push to all followers' feeds
    for f_id in get_follower_user_ids(photo.user):
        push_to_feed_cache(f_id, photo.id)


@receiver(photo_deleted)
def _handle_photo_deleted(sender, user, **kwargs):
    follower_count = getattr(user, "profile", None)
    follower_count = follower_count.follower_count if follower_count else 0

    invalidate_feed_cache(user.id)

    if follower_count > CELEBRITY_FOLLOWER_THRESHOLD:
        return

    for f_id in get_follower_user_ids(user):
        invalidate_feed_cache(f_id)


@receiver(invitation_accepted)
def _handle_invitation_accepted(sender, user, **kwargs):
    cache.delete(f"feed:{user.id}")
