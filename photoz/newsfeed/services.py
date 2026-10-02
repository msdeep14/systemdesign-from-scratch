import contextlib
import logging
import time

from django.core.cache import cache
from redis import exceptions as redis_exceptions

from communities.services import get_accepted_community_ids
from photos.services import get_celebrity_photo_ids, get_feed_photo_ids
from stories.services import get_active_stories_for_users
from users.services import get_celebrity_followed_ids, get_followed_user_ids

logger = logging.getLogger("bses")

CELEBRITY_FOLLOWER_THRESHOLD = 10_000
CELEBRITY_IDS_CACHE_TTL = 300  # 5 minutes
CELEBRITY_FEED_PHOTO_LIMIT = 20


def _get_redis_client():
    if hasattr(cache, "client") and hasattr(cache.client, "get_client"):
        return cache.client.get_client()
    return None


@contextlib.contextmanager
def handle_redis_error(msg_template, key):
    try:
        yield
    except (redis_exceptions.RedisError, ValueError) as e:
        logger.error(msg_template, key, e)


def _get_feed_from_redis(client, cache_key):
    with handle_redis_error("Redis lrange failed for %s: %s", cache_key):
        if client.type(cache_key) == b"string":
            client.delete(cache_key)

        photo_ids_raw = client.lrange(cache_key, 0, -1)
        if photo_ids_raw:
            return [int(pid) for pid in photo_ids_raw]
    return None


def _populate_feed(user_id):
    followed_users = get_followed_user_ids(user_id)
    my_communities = get_accepted_community_ids(user_id)
    return get_feed_photo_ids(user_id, followed_users, my_communities)


def _save_feed_to_redis(client, cache_key, photo_ids):
    with handle_redis_error("Redis rpush failed for %s: %s", cache_key):
        if photo_ids:
            client.delete(cache_key)
            client.rpush(cache_key, *photo_ids)
            client.expire(cache_key, 3600)


def _wait_for_feed_promise(client, cache_key):
    for _ in range(20):
        time.sleep(0.05)
        try:
            photo_ids_raw = client.lrange(cache_key, 0, -1)
            if photo_ids_raw:
                return [int(pid) for pid in photo_ids_raw]
        except (redis_exceptions.RedisError, ValueError):
            break
    logger.warning(
        "Cache promise timeout for %s. Returning 503 to prevent Thundering Herd.",
        cache_key,
    )
    return None


def get_celebrity_user_ids(user_id: int) -> list[int]:
    """
    Returns IDs of celebrity accounts (above follower threshold) that this user follows.
    Result is cached in Redis per user with a short TTL.
    """
    cache_key = f"celebrity_ids:{user_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    celebrity_ids = get_celebrity_followed_ids(user_id, CELEBRITY_FOLLOWER_THRESHOLD)
    cache.set(cache_key, celebrity_ids, timeout=CELEBRITY_IDS_CACHE_TTL)
    return celebrity_ids


def get_cached_feed(user_id):
    """
    Fetches the feed photo IDs for a user.
    Merges push-based Redis feed (regular users) with pull-based DB query (celebrity users).
    Falls back to a 503 if cache population fails (thundering herd prevention).
    Returns a list of photo IDs, or None if the feed is currently generating.
    """
    client = _get_redis_client()
    cache_key = f":1:feed:{user_id}" if client else f"feed:{user_id}"
    lock_key = f":1:lock:feed:{user_id}"

    photo_ids = _get_feed_from_redis(client, cache_key) if client else cache.get(cache_key)

    if photo_ids is None:
        acquired = True
        if client:
            with handle_redis_error("Redis lock failed for %s: %s", lock_key):
                acquired = client.set(lock_key, b"1", nx=True, ex=5)

        if acquired:
            try:
                photo_ids = _populate_feed(user_id)
                if client:
                    _save_feed_to_redis(client, cache_key, photo_ids)
                else:
                    cache.set(cache_key, photo_ids, timeout=3600)
            finally:
                if client:
                    with contextlib.suppress(redis_exceptions.RedisError):
                        client.delete(lock_key)
        else:
            photo_ids = _wait_for_feed_promise(client, cache_key)

    if photo_ids is None:
        return None

    # Pull celebrity photos at read time and merge
    celebrity_ids = get_celebrity_user_ids(user_id)
    if celebrity_ids:
        celeb_photo_ids = get_celebrity_photo_ids(celebrity_ids, limit=CELEBRITY_FEED_PHOTO_LIMIT)
        if celeb_photo_ids:
            merged = list(dict.fromkeys(celeb_photo_ids + photo_ids))
            return merged

    return photo_ids


def push_to_feed_cache(user_id, photo_id):
    """Pushes a new photo ID to a user's cached feed in Redis."""
    client = _get_redis_client()
    if not client:
        return

    cache_key = f":1:feed:{user_id}"
    with handle_redis_error("Failed to update redis cache on upload: %s (key: %s)", cache_key):
        if client.exists(cache_key):
            if client.type(cache_key) == b"list":
                client.lpush(cache_key, photo_id)
                client.ltrim(cache_key, 0, 999)
            else:
                logger.warning("Cache key %s is not a list. Deleting.", cache_key)
                client.delete(cache_key)


def push_to_feed_cache_bulk(user_ids, photo_id):
    """Pushes a new photo ID to multiple users' cached feeds using Redis pipelining."""
    client = _get_redis_client()
    if not client or not user_ids:
        return

    cache_keys = [f":1:feed:{uid}" for uid in user_ids]

    # Phase 1: Pipeline to check which feed caches actually exist
    # (We ignore cold caches so we don't create 1-item partial feeds)
    pipeline = client.pipeline(transaction=False)
    for key in cache_keys:
        pipeline.exists(key)

    with handle_redis_error("Failed bulk redis pipeline (exists)", "multiple"):
        exists_results = pipeline.execute()

    # Phase 2: Pipeline to execute LPUSH and LTRIM only on warm caches
    pipeline = client.pipeline(transaction=False)
    commands_queued = False
    for key, exists in zip(cache_keys, exists_results, strict=False):
        if exists:
            pipeline.lpush(key, photo_id)
            pipeline.ltrim(key, 0, 999)
            commands_queued = True

    if commands_queued:
        with handle_redis_error("Failed bulk redis pipeline (push)", "multiple"):
            pipeline.execute()


def invalidate_feed_cache(user_id):
    """Invalidates the feed cache for a user."""
    cache.delete(f"feed:{user_id}")


def get_feed_stories_grouped(user_id):
    followed_user_ids = get_followed_user_ids(user_id)
    story_user_ids = list(followed_user_ids) + [user_id]
    return get_active_stories_for_users(story_user_ids)
