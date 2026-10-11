"""Signal receivers dispatching notification events to Kafka."""

from django.dispatch import receiver

from bses.kafka import publish_kafka_event
from communities.signals import member_invited
from photos.signals import photo_commented, photo_liked, user_tagged
from stories.signals import story_user_tagged


@receiver(photo_liked)
def _handle_photo_liked(sender, photo, liker, **kwargs):
    publish_kafka_event(
        "notifications",
        {
            "event_type": "photo_activity",
            "photo_id": photo.id,
            "actor_id": liker.id,
            "notif_type": "photo_like",
            "verb": "liked",
        },
        key=str(photo.user_id),
    )


@receiver(photo_commented)
def _handle_photo_commented(sender, photo, commenter, **kwargs):
    publish_kafka_event(
        "notifications",
        {
            "event_type": "photo_activity",
            "photo_id": photo.id,
            "actor_id": commenter.id,
            "notif_type": "photo_comment",
            "verb": "commented on",
        },
        key=str(photo.user_id),
    )


@receiver(member_invited)
def _handle_member_invited(sender, community, target_user, inviter, membership, **kwargs):
    publish_kafka_event(
        "notifications",
        {
            "event_type": "member_invited",
            "community_id": community.id,
            "target_user_id": target_user.id,
            "inviter_id": inviter.id,
            "membership_id": membership.id,
        },
        key=str(target_user.id),
    )


@receiver(user_tagged)
def _handle_user_tagged(sender, photo, tagged_user, tagger, **kwargs):
    publish_kafka_event(
        "notifications",
        {
            "event_type": "tagged",
            "object_id": photo.id,
            "tagged_user_id": tagged_user.id,
            "tagger_id": tagger.id,
            "object_type": "photo",
        },
        key=str(tagged_user.id),
    )


@receiver(story_user_tagged)
def _handle_story_user_tagged(sender, story, tagged_user, tagger, **kwargs):
    publish_kafka_event(
        "notifications",
        {
            "event_type": "tagged",
            "object_id": story.id,
            "tagged_user_id": tagged_user.id,
            "tagger_id": tagger.id,
            "object_type": "story",
        },
        key=str(tagged_user.id),
    )
