from unittest.mock import MagicMock, patch

from django.test import TestCase

from bses import redis_client


class RedisSentinelTestCase(TestCase):
    def setUp(self):
        # Reset module-level singletons between tests
        redis_client.reset_singletons()

    def test_standalone_redis_fallback_returns_singleton(self):
        with patch("bses.redis_client.settings") as mock_settings:
            mock_settings.REDIS_SENTINELS = []
            mock_settings.REDIS_URL = "redis://localhost:6379/1"
            mock_settings.REDIS_SOCKET_TIMEOUT = 0.5
            mock_settings.REDIS_CONNECT_TIMEOUT = 0.5
            mock_settings.REDIS_HEALTH_CHECK_INTERVAL = 30
            mock_settings.REDIS_MAX_CONNECTIONS_MASTER = 20

            with (
                patch("bses.redis_client.redis.ConnectionPool.from_url") as mock_pool_from_url,
                patch("bses.redis_client.redis.StrictRedis") as mock_redis_cls,
            ):
                mock_pool = MagicMock()
                mock_pool_from_url.return_value = mock_pool
                mock_client = MagicMock()
                mock_redis_cls.return_value = mock_client

                master1 = redis_client.get_redis_master()
                master2 = redis_client.get_redis_master()
                replica = redis_client.get_redis_replica()

                # Verify singleton behavior (reusing the same connection pool)
                self.assertEqual(master1, mock_client)
                self.assertEqual(master2, mock_client)
                self.assertEqual(replica, mock_client)
                mock_pool_from_url.assert_called_once()

    def test_sentinel_resolution_with_connection_pool_safeguards(self):
        with patch("bses.redis_client.settings") as mock_settings:
            mock_settings.REDIS_SENTINELS = [("sentinel1", 26379), ("sentinel2", 26379)]
            mock_settings.REDIS_MASTER_NAME = "mymaster"
            mock_settings.REDIS_SOCKET_TIMEOUT = 0.5
            mock_settings.REDIS_CONNECT_TIMEOUT = 0.5
            mock_settings.REDIS_HEALTH_CHECK_INTERVAL = 30
            mock_settings.REDIS_MAX_CONNECTIONS_MASTER = 20
            mock_settings.REDIS_MAX_CONNECTIONS_REPLICA = 50

            with patch("bses.redis_client.Sentinel") as mock_sentinel_cls:
                mock_sentinel = MagicMock()
                mock_sentinel_cls.return_value = mock_sentinel
                mock_master = MagicMock()
                mock_replica = MagicMock()
                mock_sentinel.master_for.return_value = mock_master
                mock_sentinel.slave_for.return_value = mock_replica

                master1 = redis_client.get_redis_master()
                master2 = redis_client.get_redis_master()
                replica1 = redis_client.get_redis_replica()
                replica2 = redis_client.get_redis_replica()

                # Verify strict timeout kwargs and pool options passed to master_for
                mock_sentinel.master_for.assert_called_once_with(
                    "mymaster",
                    decode_responses=True,
                    socket_timeout=0.5,
                    socket_connect_timeout=0.5,
                    health_check_interval=30,
                    max_connections=20,
                )
                # Verify sized read replica pool options passed to slave_for
                mock_sentinel.slave_for.assert_called_once_with(
                    "mymaster",
                    decode_responses=True,
                    socket_timeout=0.5,
                    socket_connect_timeout=0.5,
                    health_check_interval=30,
                    max_connections=50,
                )

                # Verify singletons are returned on subsequent calls
                self.assertEqual(master1, master2)
                self.assertEqual(replica1, replica2)
