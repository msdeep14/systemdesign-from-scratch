from celery import shared_task
from django.contrib.auth.models import User

from communities.models import Community, CommunityMembership
from notifications.models import Notification
from photos.models import Photo
from stories.models import Story


@shared_task
def send_photo_liked_notification_task(photo_id: int, liker_id: int):
    try:
        photo = Photo.objects.get(id=photo_id)
        liker = User.objects.get(id=liker_id)
        Notification.objects.create(
            recipient=photo.user,
            sender=liker,
            type="photo_like",
            message=f"{liker.profile.first_name} liked your photo.",
            photo=photo,
        )
    except (Photo.DoesNotExist, User.DoesNotExist):
        pass


@shared_task
def send_photo_commented_notification_task(photo_id: int, commenter_id: int):
    try:
        photo = Photo.objects.get(id=photo_id)
        commenter = User.objects.get(id=commenter_id)
        Notification.objects.create(
            recipient=photo.user,
            sender=commenter,
            type="photo_comment",
            message=f"{commenter.profile.first_name} commented on your photo.",
            photo=photo,
        )
    except (Photo.DoesNotExist, User.DoesNotExist):
        pass


@shared_task
def send_member_invited_notification_task(
    community_id: int, target_user_id: int, inviter_id: int, membership_id: int
):
    try:
        community = Community.objects.get(id=community_id)
        target_user = User.objects.get(id=target_user_id)
        inviter = User.objects.get(id=inviter_id)
        membership = CommunityMembership.objects.get(id=membership_id)

        Notification.objects.create(
            recipient=target_user,
            sender=inviter,
            type="community_invite",
            message=f"{inviter.profile.first_name} invited you to join '{community.name}'.",
            membership=membership,
        )
    except (Community.DoesNotExist, User.DoesNotExist, CommunityMembership.DoesNotExist):
        pass


@shared_task
def send_user_tagged_notification_task(photo_id: int, tagged_user_id: int, tagger_id: int):
    try:
        photo = Photo.objects.get(id=photo_id)
        tagged_user = User.objects.get(id=tagged_user_id)
        tagger = User.objects.get(id=tagger_id)

        Notification.objects.create(
            recipient=tagged_user,
            sender=tagger,
            type="photo_tag",
            message=f"{tagger.profile.first_name} tagged you in a photo.",
            photo=photo,
        )
    except (Photo.DoesNotExist, User.DoesNotExist):
        pass


@shared_task
def send_story_user_tagged_notification_task(story_id: int, tagged_user_id: int, tagger_id: int):
    try:
        story = Story.objects.get(id=story_id)
        tagged_user = User.objects.get(id=tagged_user_id)
        tagger = User.objects.get(id=tagger_id)

        Notification.objects.create(
            recipient=tagged_user,
            sender=tagger,
            type="story_tag",
            message=f"{tagger.profile.first_name} tagged you in a story.",
            story=story,
        )
    except (Story.DoesNotExist, User.DoesNotExist):
        pass
