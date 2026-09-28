from celery import shared_task
from django.contrib.auth.models import User

from communities.models import Community, CommunityMembership
from notifications.models import Notification
from photos.models import Photo
from stories.models import Story


@shared_task
def send_photo_activity_notification_task(photo_id: int, actor_id: int, notif_type: str, verb: str):
    try:
        photo = Photo.objects.get(id=photo_id)
        actor = User.objects.get(id=actor_id)
        Notification.objects.create(
            recipient=photo.user,
            sender=actor,
            type=notif_type,
            message=f"{actor.profile.first_name} {verb} your photo.",
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
def send_tagged_notification_task(
    object_id: int, tagged_user_id: int, tagger_id: int, object_type: str
):
    try:
        tagged_user = User.objects.get(id=tagged_user_id)
        tagger = User.objects.get(id=tagger_id)

        notif_type = f"{object_type}_tag"
        message = f"{tagger.profile.first_name} tagged you in a {object_type}."

        notif_kwargs = {
            "recipient": tagged_user,
            "sender": tagger,
            "type": notif_type,
            "message": message,
        }

        if object_type == "photo":
            notif_kwargs["photo"] = Photo.objects.get(id=object_id)
        elif object_type == "story":
            notif_kwargs["story"] = Story.objects.get(id=object_id)

        Notification.objects.create(**notif_kwargs)
    except (Photo.DoesNotExist, Story.DoesNotExist, User.DoesNotExist):
        pass
