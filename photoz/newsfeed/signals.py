from django.core.cache import cache
from django.dispatch import receiver

from communities.signals import invitation_accepted
from newsfeed.services import invalidate_feed_cache, push_to_feed_cache
from photos.signals import photo_deleted, photo_uploaded
from users.services import get_follower_user_ids


@receiver(photo_uploaded)
def _handle_photo_uploaded(sender, photo, **kwargs):
    # Fan-out on write: add photo to user's feed and all followers' feeds
    push_to_feed_cache(photo.user.id, photo.id)
    follower_ids = get_follower_user_ids(photo.user)
    for f_id in follower_ids:
        push_to_feed_cache(f_id, photo.id)


@receiver(photo_deleted)
def _handle_photo_deleted(sender, user, **kwargs):
    # Clear cache for the user and their followers
    follower_ids = get_follower_user_ids(user)
    for f_id in follower_ids:
        invalidate_feed_cache(f_id)
    invalidate_feed_cache(user.id)


@receiver(invitation_accepted)
def _handle_invitation_accepted(sender, user, **kwargs):
    # Invalidate newsfeed cache so new community posts show up
    cache.delete(f"feed:{user.id}")
