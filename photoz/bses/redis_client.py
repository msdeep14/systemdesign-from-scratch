import os

import redis
from django.conf import settings
from redis.sentinel import Sentinel


def _parse_sentinels(sentinels_str: str) -> list[tuple[str, int]]:
    """Parse comma-separated host:port string into a list of tuples."""
    if not sentinels_str:
        return []
    hosts = []
    for item in sentinels_str.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 26379
        hosts.append((host, port))
    return hosts


# pylint: disable=too-many-instance-attributes
class RedisClientManager:
    """Manages Redis connection pools and singletons for Sentinel and standalone mode."""

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        sentinels: list[tuple[str, int]] | None = None,
        master_name: str | None = None,
        redis_url: str | None = None,
        socket_timeout: float | None = None,
        socket_connect_timeout: float | None = None,
        health_check_interval: int | None = None,
        max_connections_master: int | None = None,
        max_connections_replica: int | None = None,
    ) -> None:
        self.custom_sentinels = sentinels
        self.custom_master_name = master_name
        self.custom_redis_url = redis_url
        self.custom_socket_timeout = socket_timeout
        self.custom_socket_connect_timeout = socket_connect_timeout
        self.custom_health_check_interval = health_check_interval
        self.custom_max_connections_master = max_connections_master
        self.custom_max_connections_replica = max_connections_replica

        self.sentinel_instance: Sentinel | None = None
        self.standalone_master: redis.StrictRedis | None = None
        self.master_client: redis.StrictRedis | None = None
        self.replica_client: redis.StrictRedis | None = None

    def reset_singletons(self) -> None:
        """Reset cached singletons. Intended for use in tests."""
        self.sentinel_instance = None
        self.standalone_master = None
        self.master_client = None
        self.replica_client = None

    def get_sentinel(self) -> Sentinel | None:
        """Return a singleton Sentinel instance or None if not configured."""
        if self.custom_sentinels is not None:
            sentinels = self.custom_sentinels
        else:
            sentinels = getattr(settings, "REDIS_SENTINELS", None)
            if not sentinels:
                env_sentinels = os.environ.get("REDIS_SENTINELS", "")
                sentinels = _parse_sentinels(env_sentinels)

        if not sentinels:
            return None

        if self.sentinel_instance is None:
            socket_timeout = (
                self.custom_socket_timeout
                if self.custom_socket_timeout is not None
                else getattr(settings, "REDIS_SOCKET_TIMEOUT", 0.5)
            )
            socket_connect_timeout = (
                self.custom_socket_connect_timeout
                if self.custom_socket_connect_timeout is not None
                else getattr(settings, "REDIS_CONNECT_TIMEOUT", 0.5)
            )
            self.sentinel_instance = Sentinel(
                sentinels,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
            )
        return self.sentinel_instance

    def get_redis_master(self) -> redis.StrictRedis:
        """Return singleton Redis client connected to the primary writer."""
        sentinel = self.get_sentinel()
        socket_timeout = (
            self.custom_socket_timeout
            if self.custom_socket_timeout is not None
            else getattr(settings, "REDIS_SOCKET_TIMEOUT", 0.5)
        )
        socket_connect_timeout = (
            self.custom_socket_connect_timeout
            if self.custom_socket_connect_timeout is not None
            else getattr(settings, "REDIS_CONNECT_TIMEOUT", 0.5)
        )
        health_check_interval = (
            self.custom_health_check_interval
            if self.custom_health_check_interval is not None
            else getattr(settings, "REDIS_HEALTH_CHECK_INTERVAL", 30)
        )
        max_connections = (
            self.custom_max_connections_master
            if self.custom_max_connections_master is not None
            else getattr(settings, "REDIS_MAX_CONNECTIONS_MASTER", 20)
        )

        if sentinel:
            if self.master_client is None:
                master_name = (
                    self.custom_master_name
                    if self.custom_master_name is not None
                    else getattr(settings, "REDIS_MASTER_NAME", "mymaster")
                )
                self.master_client = sentinel.master_for(
                    master_name,
                    decode_responses=True,
                    socket_timeout=socket_timeout,
                    socket_connect_timeout=socket_connect_timeout,
                    health_check_interval=health_check_interval,
                    max_connections=max_connections,
                )
            return self.master_client

        if self.standalone_master is None:
            redis_url = (
                self.custom_redis_url
                if self.custom_redis_url is not None
                else getattr(settings, "REDIS_URL", "redis://localhost:6379/1")
            )
            pool = redis.ConnectionPool.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
                health_check_interval=health_check_interval,
                max_connections=max_connections,
            )
            self.standalone_master = redis.StrictRedis(connection_pool=pool)
        return self.standalone_master

    def get_redis_replica(self) -> redis.StrictRedis:
        """Return singleton Redis client connected to a read replica."""
        sentinel = self.get_sentinel()
        if sentinel:
            if self.replica_client is None:
                master_name = (
                    self.custom_master_name
                    if self.custom_master_name is not None
                    else getattr(settings, "REDIS_MASTER_NAME", "mymaster")
                )
                socket_timeout = (
                    self.custom_socket_timeout
                    if self.custom_socket_timeout is not None
                    else getattr(settings, "REDIS_SOCKET_TIMEOUT", 0.5)
                )
                socket_connect_timeout = (
                    self.custom_socket_connect_timeout
                    if self.custom_socket_connect_timeout is not None
                    else getattr(settings, "REDIS_CONNECT_TIMEOUT", 0.5)
                )
                health_check_interval = (
                    self.custom_health_check_interval
                    if self.custom_health_check_interval is not None
                    else getattr(settings, "REDIS_HEALTH_CHECK_INTERVAL", 30)
                )
                max_connections = (
                    self.custom_max_connections_replica
                    if self.custom_max_connections_replica is not None
                    else getattr(settings, "REDIS_MAX_CONNECTIONS_REPLICA", 50)
                )

                self.replica_client = sentinel.slave_for(
                    master_name,
                    decode_responses=True,
                    socket_timeout=socket_timeout,
                    socket_connect_timeout=socket_connect_timeout,
                    health_check_interval=health_check_interval,
                    max_connections=max_connections,
                )
            return self.replica_client

        return self.get_redis_master()


DEFAULT_MANAGER = RedisClientManager()


def reset_singletons() -> None:
    """Reset cached singletons. Intended for use in tests."""
    DEFAULT_MANAGER.reset_singletons()


def get_sentinel() -> Sentinel | None:
    """Return a singleton Sentinel instance or None if not configured."""
    return DEFAULT_MANAGER.get_sentinel()


def get_redis_master() -> redis.StrictRedis:
    """Return singleton Redis client connected to the primary writer."""
    return DEFAULT_MANAGER.get_redis_master()


def get_redis_replica() -> redis.StrictRedis:
    """Return singleton Redis client connected to a read replica."""
    return DEFAULT_MANAGER.get_redis_replica()
