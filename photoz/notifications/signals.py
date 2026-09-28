from django.dispatch import receiver

from communities.signals import member_invited
from notifications.tasks import (
    send_member_invited_notification_task,
    send_photo_activity_notification_task,
    send_tagged_notification_task,
)
from photos.signals import photo_commented, photo_liked, user_tagged
from stories.signals import story_user_tagged


@receiver(photo_liked)
def _handle_photo_liked(sender, photo, liker, **kwargs):
    send_photo_activity_notification_task.delay(photo.id, liker.id, "photo_like", "liked")


@receiver(photo_commented)
def _handle_photo_commented(sender, photo, commenter, **kwargs):
    send_photo_activity_notification_task.delay(
        photo.id, commenter.id, "photo_comment", "commented on"
    )


@receiver(member_invited)
def _handle_member_invited(sender, community, target_user, inviter, membership, **kwargs):
    send_member_invited_notification_task.delay(
        community.id, target_user.id, inviter.id, membership.id
    )


@receiver(user_tagged)
def _handle_user_tagged(sender, photo, tagged_user, tagger, **kwargs):
    send_tagged_notification_task.delay(photo.id, tagged_user.id, tagger.id, "photo")


@receiver(story_user_tagged)
def _handle_story_user_tagged(sender, story, tagged_user, tagger, **kwargs):
    send_tagged_notification_task.delay(story.id, tagged_user.id, tagger.id, "story")
