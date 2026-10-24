import json
import time
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q

from bses.redis_client import get_redis_master, get_redis_replica
from photos.models import Like, Photo

# Optional fallback client for backwards compatibility in existing tests
redis_client: object | None = None  # pylint: disable=invalid-name


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


def get_photo_likes_count(photo_id: int, db_likes_count: int) -> int:
    """Gets the live like count for a photo using Full Count strategy."""
    key = f"photo:{photo_id}:likes_count"
    read_client = redis_client or get_redis_replica()
    count = read_client.get(key)
    if count is not None:
        return int(count)

    write_client = redis_client or get_redis_master()
    write_client.set(key, db_likes_count)
    return db_likes_count


def update_like_count_redis(photo_id: int, db_likes_count: int, increment: bool = True):
    """Updates the like count for a photo in Redis."""
    key = f"photo:{photo_id}:likes_count"
    master = redis_client or get_redis_master()

    # Ensure baseline is set if it was evicted or not yet cached.
    # Uses caller's `db_likes_count` to avoid an extra DB lookup.
    if not master.exists(key):
        master.set(key, db_likes_count)

    if increment:
        master.incr(key)
    else:
        master.decr(key)
    master.sadd("photos_with_pending_like_counts", photo_id)


def is_photo_liked_by_user(photo_id: int, user_id: int) -> bool:
    """Checks whether a user has liked a photo via user-centric Redis set with DB fallback."""
    user_key = f"user:{user_id}:liked_photos"
    read_client = redis_client or get_redis_replica()
    if read_client.exists(user_key):
        return bool(read_client.sismember(user_key, str(photo_id)))

    # Cache miss: populate from PostgreSQL (user's recent 500 likes)
    liked_photo_ids = list(
        Like.objects.filter(user_id=user_id)
        .order_by("-created_at")[:500]
        .values_list("photo_id", flat=True)
    )
    write_client = redis_client or get_redis_master()
    if liked_photo_ids:
        write_client.sadd(user_key, *[str(pid) for pid in liked_photo_ids])
    else:
        write_client.sadd(user_key, "__empty__")
    write_client.expire(user_key, 86400)

    return photo_id in liked_photo_ids


def toggle_photo_like_redis(photo_id: int, user_id: int, db_likes_count: int) -> tuple[bool, int]:
    """Atomically toggle like state for user in Redis and return (has_liked, likes_count)."""
    count_key = f"photo:{photo_id}:likes_count"
    user_key = f"user:{user_id}:liked_photos"
    master = redis_client or get_redis_master()

    if not master.exists(count_key):
        master.set(count_key, db_likes_count)

    if not master.exists(user_key):
        is_photo_liked_by_user(photo_id, user_id)

    is_liked = bool(master.sismember(user_key, str(photo_id)))
    if is_liked:
        master.srem(user_key, str(photo_id))
        new_count = master.decr(count_key)
        has_liked = False
    else:
        master.sadd(user_key, str(photo_id))
        new_count = master.incr(count_key)
        has_liked = True

    master.sadd("photos_with_pending_like_counts", photo_id)
    return has_liked, max(0, new_count)


def _serialize_photo(photo: Photo) -> str:
    """Serializes a Photo object for caching."""
    return json.dumps(
        {
            "id": photo.id,
            "caption": photo.caption,
            "image_url": photo.image.url if photo.image else None,
            "created_at": photo.created_at.isoformat(),
            "user_id": photo.user_id,
            "user_username": photo.user.profile.username_display,
            "community_id": photo.community_id,
        }
    )


def get_cached_photo(photo_id: int):
    """
    Fetches the photo from cache. If missing, implements a Mutex Lock (Cache Promise)
    using Redis Pub/Sub to prevent a Thundering Herd from hitting the database.
    """
    key = f"photo:{photo_id}:data"
    read_client = redis_client or get_redis_replica()
    cached = read_client.get(key)
    if cached:
        return json.loads(cached)

    lock_key = f"lock:photo:{photo_id}"
    channel = f"channel:photo:{photo_id}:populated"
    write_client = redis_client or get_redis_master()

    # Try to acquire lock
    if write_client.setnx(lock_key, "1"):
        # We are the winner. We fetch from DB, populate cache, and publish.
        write_client.expire(lock_key, 10)  # 10s safety timeout

        # Query DB
        photo = Photo.objects.select_related("user__profile").filter(id=photo_id).first()
        if not photo:
            write_client.delete(lock_key)
            return None

        photo_data = _serialize_photo(photo)

        # Determine TTL based on celebrity status
        is_celebrity = photo.user.profile.follower_count > settings.CELEBRITY_FOLLOWER_THRESHOLD
        ttl = (
            settings.CACHE_TTL_CELEBRITY_PHOTO if is_celebrity else settings.CACHE_TTL_NORMAL_PHOTO
        )

        write_client.setex(key, ttl, photo_data)

        # Release lock and notify waiting clients via push
        write_client.delete(lock_key)
        write_client.publish(channel, "READY")

        return json.loads(photo_data)
    else:
        # We are part of the herd. Wait for the winner via Pub/Sub push notification
        pubsub = write_client.pubsub()
        pubsub.subscribe(channel)

        start_time = time.time()
        # Wait up to 5 seconds for the READY message
        while time.time() - start_time < 5.0:
            message = pubsub.get_message(timeout=1.0)
            if message and message["type"] == "message" and message["data"] == "READY":
                break

        pubsub.unsubscribe(channel)

        # Now read from the newly populated cache
        cached = read_client.get(key)
        if cached:
            return json.loads(cached)

        # Fallback if something went wrong
        photo = Photo.objects.select_related("user__profile").filter(id=photo_id).first()
        return json.loads(_serialize_photo(photo)) if photo else None


def bulk_record_likes(like_pairs: list[tuple[int, int]]) -> int:
    """Bulk create Like records and atomically increment likes_count in PostgreSQL."""
    if not like_pairs:
        return 0

    unique_pairs = list(set(like_pairs))
    existing_pairs = set(
        Like.objects.filter(
            photo_id__in=[p[0] for p in unique_pairs],
            user_id__in=[p[1] for p in unique_pairs],
        ).values_list("photo_id", "user_id")
    )
    new_pairs = [pair for pair in unique_pairs if pair not in existing_pairs]
    if not new_pairs:
        return 0

    likes_to_create = [Like(photo_id=photo_id, user_id=user_id) for photo_id, user_id in new_pairs]
    photo_counts: dict[int, int] = defaultdict(int)
    write_client = redis_client or get_redis_master()
    for photo_id, user_id in new_pairs:
        photo_counts[photo_id] += 1
        user_key = f"user:{user_id}:liked_photos"
        if write_client.exists(user_key):
            write_client.sadd(user_key, str(photo_id))

    with transaction.atomic():
        Like.objects.bulk_create(likes_to_create, ignore_conflicts=True)
        for p_id, count in photo_counts.items():
            Photo.objects.filter(id=p_id).update(likes_count=F("likes_count") + count)

    return len(new_pairs)
