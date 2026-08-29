import contextlib
import logging
import time

from django.core.cache import cache
from redis import exceptions as redis_exceptions

from communities.services import get_accepted_community_ids
from photos.services import get_feed_photo_ids
from users.services import get_followed_user_ids

logger = logging.getLogger("bses")


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


def get_cached_feed(user_id):
    """
    Fetches the feed photo IDs for a user, checking Redis/cache first.
    If a cache miss occurs, attempts to lock, fetch from DB, and cache.
    Falls back to a 503 if polling fails (Thundering herd prevention).
    Returns a list of photo IDs, or None if the feed is currently generating (503).
    """
    client = _get_redis_client()
    cache_key = f":1:feed:{user_id}" if client else f"feed:{user_id}"
    lock_key = f":1:lock:feed:{user_id}"

    photo_ids = _get_feed_from_redis(client, cache_key) if client else cache.get(cache_key)

    if photo_ids is not None:
        return photo_ids

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


def invalidate_feed_cache(user_id):
    """Invalidates the feed cache for a user."""
    cache.delete(f"feed:{user_id}")
