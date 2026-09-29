import redis
from django.conf import settings
from django.db.models import Q

from photos.models import Photo


def get_feed_photo_ids(user_id, followed_user_ids, community_ids):
    """
    Fetches the top 1000 photo IDs for a user's feed based on followed users and communities.
    """
    feed_qs = (
        Photo.objects.filter(
            Q(user_id__in=followed_user_ids, community__isnull=True)
            | Q(community_id__in=community_ids)
            | Q(user_id=user_id)
        )
        .order_by("-created_at")
        .distinct()[:1000]
    )
    return list(feed_qs.values_list("id", flat=True))


def get_photos_by_ids(photo_ids):
    """
    Returns a list of Photo objects for the given IDs, preserving the order of the IDs.
    """
    photos_qs = Photo.objects.filter(id__in=photo_ids).select_related("user__profile", "community")
    photos_dict = {p.id: p for p in photos_qs}
    return [photos_dict[pid] for pid in photo_ids if pid in photos_dict]


def get_celebrity_photo_ids(celebrity_user_ids: list[int], limit: int = 20) -> list[int]:
    """
    Returns the most recent photo IDs from celebrity accounts.
    Only public photos (no community restriction) are included.
    """
    return list(
        Photo.objects.filter(user_id__in=celebrity_user_ids, community__isnull=True)
        .order_by("-created_at")
        .values_list("id", flat=True)[:limit]
    )


redis_client = redis.StrictRedis.from_url(settings.REDIS_URL, decode_responses=True)


def get_photo_likes_count(photo_id: int, db_likes_count: int) -> int:
    """Gets the live like count for a photo using Full Count strategy."""
    key = f"photo:{photo_id}:likes_count"
    count = redis_client.get(key)
    if count is not None:
        return int(count)

    # Cache Miss: We pass `db_likes_count` from the caller (which already fetched the
    # Photo object from the DB) to avoid firing a redundant DB query inside this function.
    redis_client.set(key, db_likes_count)
    return db_likes_count


def update_like_count_redis(photo_id: int, db_likes_count: int, increment: bool = True):
    """Updates the like count for a photo in Redis."""
    key = f"photo:{photo_id}:likes_count"

    # Ensure baseline is set if it was evicted or not yet cached.
    # Uses caller's `db_likes_count` to avoid an extra DB lookup.
    if not redis_client.exists(key):
        redis_client.set(key, db_likes_count)

    if increment:
        redis_client.incr(key)
    else:
        redis_client.decr(key)
    redis_client.sadd("photos_with_pending_like_counts", photo_id)
