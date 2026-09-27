import redis
from django.conf import settings
from django.db.models import Q

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
