from collections import defaultdict

import redis
from django.conf import settings
from django.db import transaction
from django.db.models import F, Q

from users.models import Follow, UserProfile

# Initialize Redis client
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


def increment_follower_count_redis(user_id: int):
    """Increments the follower count for a user in Redis."""
    key = f"user:{user_id}:follower_count"
    redis_client.incr(key)
    redis_client.sadd("users_with_pending_follower_counts", user_id)


def decrement_follower_count_redis(user_id: int):
    """Decrements the follower count for a user in Redis."""
    key = f"user:{user_id}:follower_count"
    redis_client.decr(key)
    redis_client.sadd("users_with_pending_follower_counts", user_id)


def get_follower_count(user_id: int, db_follower_count: int) -> int:
    """Gets the live follower count for a user (Redis delta + DB baseline)."""
    key = f"user:{user_id}:follower_count"
    delta = redis_client.get(key)
    if delta is not None:
        return db_follower_count + int(delta)
    return db_follower_count


def get_followed_user_ids(user):
    """Returns a list of IDs of users that the given user follows."""
    return list(Follow.objects.filter(follower=user).values_list("following", flat=True))


def get_follower_user_ids(user):
    """Returns a list of IDs of users that follow the given user."""
    return list(Follow.objects.filter(following=user).values_list("follower_id", flat=True))


def get_celebrity_followed_ids(user_id: int, follower_threshold: int) -> list[int]:
    """Returns IDs of users above follower_threshold that this user follows."""
    return list(
        Follow.objects.filter(follower_id=user_id)
        .select_related("following__profile")
        .filter(following__profile__follower_count__gt=follower_threshold)
        .values_list("following_id", flat=True)
    )


def search_users(query):
    """Searches for users by username or name."""
    if not query:
        return []
    return list(
        UserProfile.objects.filter(
            Q(username_display__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )[:50]
    )


def get_user_profile_by_username(username):
    """Fetches a UserProfile by username display."""
    return UserProfile.objects.filter(username_display=username).first()


def bulk_record_follows(follow_pairs: list[tuple[int, int]]) -> int:
    """Bulk create Follow records and atomically update follower counts."""
    if not follow_pairs:
        return 0

    follows_to_create = [
        Follow(follower_id=follower_id, following_id=following_id)
        for follower_id, following_id in follow_pairs
    ]

    following_counts: dict[int, int] = defaultdict(int)
    for _, following_id in follow_pairs:
        following_counts[following_id] += 1

    with transaction.atomic():
        Follow.objects.bulk_create(follows_to_create, ignore_conflicts=True)
        for u_id, count in following_counts.items():
            UserProfile.objects.filter(user_id=u_id).update(
                follower_count=F("follower_count") + count
            )

    return len(follows_to_create)


def get_user_follower_count(user_id: int) -> int:
    """Returns the follower count for the given user ID."""
    profile = UserProfile.objects.filter(user_id=user_id).first()
    return profile.follower_count if profile else 0


def get_follower_ids_by_user_id(user_id: int) -> list[int]:
    """Returns a list of follower IDs for the given user ID."""
    return list(Follow.objects.filter(following_id=user_id).values_list("follower_id", flat=True))
