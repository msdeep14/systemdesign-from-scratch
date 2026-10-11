"""Notification business logic and Kafka consumer event ingestion."""

import logging
from typing import Any

from django.contrib.auth.models import User

from communities.models import Community, CommunityMembership
from notifications.models import Notification
from photos.models import Photo
from stories.models import Story

logger = logging.getLogger(__name__)


def _process_photo_activity_event(event: dict[str, Any]) -> bool:
    """Create a notification for photo like or comment activity."""
    try:
        photo = Photo.objects.select_related("user").get(id=event["photo_id"])
        actor = User.objects.select_related("profile").get(id=event["actor_id"])
        verb = event.get("verb", "interacted with")
        Notification.objects.create(
            recipient=photo.user,
            sender=actor,
            type=event.get("notif_type", "photo_like"),
            message=f"{actor.profile.first_name} {verb} your photo.",
            photo=photo,
        )
        return True
    except (Photo.DoesNotExist, User.DoesNotExist, KeyError) as err:
        logger.warning("Failed to create photo activity notification: %s", err)
        return False


def _process_member_invited_event(event: dict[str, Any]) -> bool:
    """Create a notification for community invitation."""
    try:
        community = Community.objects.get(id=event["community_id"])
        target_user = User.objects.get(id=event["target_user_id"])
        inviter = User.objects.select_related("profile").get(id=event["inviter_id"])
        membership = CommunityMembership.objects.get(id=event["membership_id"])
        Notification.objects.create(
            recipient=target_user,
            sender=inviter,
            type="community_invite",
            message=f"{inviter.profile.first_name} invited you to join '{community.name}'.",
            membership=membership,
        )
        return True
    except (
        Community.DoesNotExist,
        User.DoesNotExist,
        CommunityMembership.DoesNotExist,
        KeyError,
    ) as err:
        logger.warning("Failed to create member invited notification: %s", err)
        return False


def _process_tagged_event(event: dict[str, Any]) -> bool:
    """Create a notification for photo or story user tagging."""
    try:
        tagged_user = User.objects.get(id=event["tagged_user_id"])
        tagger = User.objects.select_related("profile").get(id=event["tagger_id"])
        object_type = event.get("object_type", "photo")
        object_id = event["object_id"]

        notif_kwargs: dict[str, Any] = {
            "recipient": tagged_user,
            "sender": tagger,
            "type": f"{object_type}_tag",
            "message": f"{tagger.profile.first_name} tagged you in a {object_type}.",
        }

        if object_type == "photo":
            notif_kwargs["photo"] = Photo.objects.get(id=object_id)
        elif object_type == "story":
            notif_kwargs["story"] = Story.objects.get(id=object_id)

        Notification.objects.create(**notif_kwargs)
        return True
    except (Photo.DoesNotExist, Story.DoesNotExist, User.DoesNotExist, KeyError) as err:
        logger.warning("Failed to create tag notification: %s", err)
        return False


def process_notification_event(event: dict[str, Any]) -> bool:
    """Route notification event to specific handler based on event_type."""
    event_type = event.get("event_type")
    if event_type == "photo_activity":
        return _process_photo_activity_event(event)
    if event_type == "member_invited":
        return _process_member_invited_event(event)
    if event_type == "tagged":
        return _process_tagged_event(event)
    logger.warning("Unknown notification event type: %s", event_type)
    return False


def bulk_create_notifications(events: list[dict[str, Any]]) -> int:
    """Process a batch of notification events, returning count of successful creations."""
    success_count = 0
    for event in events:
        if process_notification_event(event):
            success_count += 1
    return success_count
