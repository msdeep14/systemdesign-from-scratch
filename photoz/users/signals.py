from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from users.models import Follow
from users.services import decrement_follower_count_redis, increment_follower_count_redis


@receiver(post_save, sender=Follow)
def _increment_follower_count(sender, instance, created, **kwargs):
    if created:
        increment_follower_count_redis(instance.following_id)


@receiver(post_delete, sender=Follow)
def _decrement_follower_count(sender, instance, **kwargs):
    decrement_follower_count_redis(instance.following_id)
