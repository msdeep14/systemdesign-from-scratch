# drift:ignore
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import redis
from django.conf import settings
from django.core.cache import caches
from redis import exceptions as redis_exceptions

from bses.redis_client import RedisClientManager

logger = logging.getLogger(__name__)


def _log_redis_error(action: str, key: str, err: Exception) -> None:
    logger.warning("Redis %s failed for %s: %s", action, key, err)


def _serialize(value: Any) -> str:
    """Serialize value to JSON string for Redis storage."""
    return json.dumps(value)


def _deserialize(raw: str | None) -> Any:
    """Deserialize JSON string from Redis, falling back to raw string."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as err:
        logger.debug("JSON decode failed for raw string: %s", err)
        return raw


class CacheService:
    """
    Unified multi-tier cache abstraction:
    - Key-value operations for in-process memory ('local') and Redis ('core', 'feeds').
    - Provides deployment-aware Redis clients for data-structure operations.
    - Implements two-tier fallback (L1 Local -> L2 Redis -> DB) with stampede protection.
    """

    def __init__(self) -> None:
        self._managers: dict[str, RedisClientManager] = {}

    def reset_singletons(self) -> None:
        """Reset cached managers and clear local cache. Used in tests."""
        for manager in self._managers.values():
            manager.reset_singletons()
        self._managers.clear()
        if "local" in caches:
            caches["local"].clear()

    def _get_manager(self, deployment: str) -> RedisClientManager:
        if deployment not in self._managers:
            deployments_cfg = getattr(settings, "REDIS_DEPLOYMENTS", {})
            cfg = deployments_cfg.get(deployment, {})

            manager = RedisClientManager(
                sentinels=cfg.get("SENTINELS"),
                master_name=cfg.get("MASTER_NAME"),
                redis_url=cfg.get("URL"),
                socket_timeout=cfg.get("SOCKET_TIMEOUT"),
                socket_connect_timeout=cfg.get("CONNECT_TIMEOUT"),
            )
            self._managers[deployment] = manager
        return self._managers[deployment]

    def get_client(self, deployment: str = "core", for_write: bool = False) -> redis.StrictRedis:
        """Return Redis client for specific deployment (handling master/replica routing)."""
        manager = self._get_manager(deployment)
        return manager.get_redis_master() if for_write else manager.get_redis_replica()

    def get(self, key: str, tier: str = "core", default: Any = None) -> Any:
        """Get value from specified cache tier."""
        if tier == "local":
            return caches["local"].get(key, default)
        client = self.get_client(deployment=tier, for_write=False)
        try:
            raw = client.get(key)
            val = _deserialize(raw)
            return val if val is not None else default
        except (redis_exceptions.RedisError, ValueError) as err:
            _log_redis_error("get", key, err)
            return default

    def set(self, key: str, value: Any, timeout: int | None = None, tier: str = "core") -> None:
        """Set value in specified cache tier."""
        if tier == "local":
            caches["local"].set(key, value, timeout=timeout)
            return
        client = self.get_client(deployment=tier, for_write=True)
        serialized = _serialize(value)
        try:
            if timeout is not None:
                client.set(key, serialized, ex=timeout)
            else:
                client.set(key, serialized)
        except (redis_exceptions.RedisError, ValueError) as err:
            _log_redis_error("set", key, err)
            return

    def delete(self, key: str, tier: str = "core") -> None:
        """Delete key from specified cache tier."""
        if tier == "local":
            caches["local"].delete(key)
            return
        client = self.get_client(deployment=tier, for_write=True)
        try:
            client.delete(key)
        except (redis_exceptions.RedisError, ValueError) as err:
            _log_redis_error("delete", key, err)
            return

    def _wait_for_promise(
        self,
        tier: str,
        key: str,
        timeout: float = 1.0,
        local_timeout: int = 5,
    ) -> Any:
        """Poll Redis for a key populated by another worker/thread (Cache Promise pattern)."""
        iterations = max(1, int(timeout / 0.05))
        for _ in range(iterations):
            time.sleep(0.05)
            val = self.get(key, tier=tier)
            if val is not None:
                self.set(key, val, timeout=local_timeout, tier="local")
                return val
        return None

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def get_or_set(
        self,
        key: str,
        default_fn: Callable[[], Any],
        local_timeout: int = 5,
        redis_timeout: int = 60,
        tier: str = "core",
        stampede_protection: bool = False,
        promise_timeout: float = 1.0,
    ) -> Any:
        """
        Two-tier lookup:
        1. Check L1 local cache.
        2. Check L2 Redis cache. If hit, backfill L1 and return.
        3. If miss, compute fresh value via default_fn and backfill both tiers.
        If stampede_protection is True, acquires a Redis lock so only one worker queries DB.
        """
        # 1. Check L1 Local Cache
        local_val = self.get(key, tier="local")
        if local_val is not None:
            return local_val

        # 2. Check L2 Redis Cache
        redis_val = self.get(key, tier=tier)
        if redis_val is not None:
            self.set(key, redis_val, timeout=local_timeout, tier="local")
            return redis_val

        # 3. Handle Cache Miss without lock
        if not stampede_protection:
            fresh_val = default_fn()
            if fresh_val is not None:
                self.set(key, fresh_val, timeout=redis_timeout, tier=tier)
                self.set(key, fresh_val, timeout=local_timeout, tier="local")
            return fresh_val

        # 4. Handle Cache Miss with Thundering Herd Protection (Single-Flight Lock)
        lock_key = f"lock:{key}"
        write_client = self.get_client(deployment=tier, for_write=True)
        acquired = False
        try:
            acquired = bool(write_client.set(lock_key, "1", nx=True, ex=5))
        except (redis_exceptions.RedisError, ValueError) as err:
            _log_redis_error("lock", lock_key, err)
            return default_fn()

        if acquired:
            try:
                fresh_val = default_fn()
            except Exception as err:
                self.delete(lock_key, tier=tier)
                _log_redis_error("compute", lock_key, err)
                raise
            self.delete(lock_key, tier=tier)
            if fresh_val is not None:
                self.set(key, fresh_val, timeout=redis_timeout, tier=tier)
                self.set(key, fresh_val, timeout=local_timeout, tier="local")
            return fresh_val
        else:
            return self._wait_for_promise(
                tier=tier,
                key=key,
                timeout=promise_timeout,
                local_timeout=local_timeout,
            )


cache_service = CacheService()


def get_cache_service() -> CacheService:
    """Return the global CacheService singleton."""
    return cache_service
