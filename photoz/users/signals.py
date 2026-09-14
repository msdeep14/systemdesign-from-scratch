from django.db.models import F
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from users.models import Follow, UserProfile


@receiver(post_save, sender=Follow)
def _increment_follower_count(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.filter(user=instance.following).update(
            follower_count=F("follower_count") + 1
        )


@receiver(post_delete, sender=Follow)
def _decrement_follower_count(sender, instance, **kwargs):
    UserProfile.objects.filter(user=instance.following).update(
        follower_count=F("follower_count") - 1
    )
