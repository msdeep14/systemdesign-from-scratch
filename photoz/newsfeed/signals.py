"""Signal handlers for newsfeed invalidation and events."""

from django.core.cache import cache
from django.dispatch import receiver

from bses.kafka import publish_kafka_event
from communities.signals import invitation_accepted
from newsfeed.services import (
    CELEBRITY_FOLLOWER_THRESHOLD,
    invalidate_feed_cache,
)
from photos.signals import photo_deleted


@receiver(photo_deleted)
def _handle_photo_deleted(sender, user, **kwargs):
    follower_count = getattr(user, "profile", None)
    follower_count = follower_count.follower_count if follower_count else 0

    invalidate_feed_cache(user.id)

    if follower_count > CELEBRITY_FOLLOWER_THRESHOLD:
        return

    photo_id = kwargs.get("photo_id", 0)
    publish_kafka_event(
        "deletions",
        {"user_id": user.id, "photo_id": photo_id},
        key=str(user.id),
    )


@receiver(invitation_accepted)
def _handle_invitation_accepted(sender, user, **kwargs):
    cache.delete(f"feed:{user.id}")
