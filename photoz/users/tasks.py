from celery import shared_task
from django.db import transaction
from django.db.models import F

from users.models import UserProfile
from users.services import redis_client


@shared_task
def flush_follower_counts_task():
    """
    Flushes the pending follower count deltas from Redis into the PostgreSQL database.
    This runs periodically via Celery Beat.
    """
    pending_users = redis_client.smembers("users_with_pending_follower_counts")
    if not pending_users:
        return 0

    updates_count = 0
    with transaction.atomic():
        for user_id_str in pending_users:
            user_id = int(user_id_str)
            key = f"user:{user_id}:follower_count"

            # Use GETSET (or pipeline) to reset the delta to 0 and get the current delta
            # This ensures we don't lose increments that happen during the flush
            delta = redis_client.getdel(key)

            if delta and int(delta) != 0:
                delta_val = int(delta)
                UserProfile.objects.filter(user_id=user_id).update(
                    follower_count=F("follower_count") + delta_val
                )
                updates_count += 1

            # Remove from pending set
            redis_client.srem("users_with_pending_follower_counts", user_id_str)

    return updates_count
