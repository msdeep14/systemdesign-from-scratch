from django.dispatch import receiver

from communities.signals import member_invited
from notifications.models import Notification
from photos.signals import photo_commented, photo_liked, user_tagged
from stories.signals import story_user_tagged


@receiver(photo_liked)
def _handle_photo_liked(sender, photo, liker, **kwargs):
    Notification.objects.create(
        recipient=photo.user,
        sender=liker,
        type="photo_like",
        message=f"{liker.profile.first_name} liked your photo.",
        photo=photo,
    )


@receiver(photo_commented)
def _handle_photo_commented(sender, photo, commenter, **kwargs):
    Notification.objects.create(
        recipient=photo.user,
        sender=commenter,
        type="photo_comment",
        message=f"{commenter.profile.first_name} commented on your photo.",
        photo=photo,
    )


@receiver(member_invited)
def _handle_member_invited(sender, community, target_user, inviter, membership, **kwargs):
    Notification.objects.create(
        recipient=target_user,
        sender=inviter,
        type="community_invite",
        message=f"{inviter.profile.first_name} invited you to join '{community.name}'.",
        membership=membership,
    )


@receiver(user_tagged)
def _handle_user_tagged(sender, photo, tagged_user, tagger, **kwargs):
    Notification.objects.create(
        recipient=tagged_user,
        sender=tagger,
        type="photo_tag",
        message=f"{tagger.profile.first_name} tagged you in a photo.",
        photo=photo,
    )


@receiver(story_user_tagged)
def _handle_story_user_tagged(sender, story, tagged_user, tagger, **kwargs):
    Notification.objects.create(
        recipient=tagged_user,
        sender=tagger,
        type="story_tag",
        message=f"{tagger.profile.first_name} tagged you in a story.",
        story=story,
    )
