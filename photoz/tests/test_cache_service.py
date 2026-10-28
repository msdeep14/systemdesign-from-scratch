from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from bses.cache import CacheService, cache_service


class CacheServiceTestCase(TestCase):
    def setUp(self):
        self.service = CacheService()
        self.service.reset_singletons()

    def tearDown(self):
        self.service.reset_singletons()
        cache_service.reset_singletons()

    def test_local_tier_get_set_delete(self):
        self.service.set("test_key", "local_value", timeout=10, tier="local")
        self.assertEqual(self.service.get("test_key", tier="local"), "local_value")

        self.service.delete("test_key", tier="local")
        self.assertIsNone(self.service.get("test_key", tier="local"))

    def test_local_tier_get_or_set_executes_once(self):
        call_count = 0

        def fetcher():
            nonlocal call_count
            call_count += 1
            return [101, 102]

        val1 = self.service.get_or_set("celeb_photos", fetcher, local_timeout=10, tier="local")
        val2 = self.service.get_or_set("celeb_photos", fetcher, local_timeout=10, tier="local")

        self.assertEqual(val1, [101, 102])
        self.assertEqual(val2, [101, 102])
        self.assertEqual(call_count, 1)

    def test_get_or_set_redis_hit_backfills_local(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = '["photo1", "photo2"]'

        with patch.object(self.service, "get_client", return_value=mock_redis):
            val = self.service.get_or_set(
                "shared_photos",
                lambda: ["fresh1"],
                local_timeout=10,
                redis_timeout=60,
                tier="core",
            )
            self.assertEqual(val, ["photo1", "photo2"])

            # Verify local tier was backfilled
            local_cached = self.service.get("shared_photos", tier="local")
            self.assertEqual(local_cached, ["photo1", "photo2"])

    def test_get_or_set_miss_populates_both_tiers(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch.object(self.service, "get_client", return_value=mock_redis):
            val = self.service.get_or_set(
                "fresh_data",
                lambda: {"status": "ok", "items": [1, 2]},
                local_timeout=10,
                redis_timeout=60,
                tier="core",
            )
            self.assertEqual(val, {"status": "ok", "items": [1, 2]})

            # Verify saved to Redis
            mock_redis.set.assert_called_once()
            args, kwargs = mock_redis.set.call_args
            self.assertEqual(args[0], "fresh_data")
            self.assertEqual(kwargs.get("ex"), 60)

            # Verify saved to local
            self.assertEqual(
                self.service.get("fresh_data", tier="local"), {"status": "ok", "items": [1, 2]}
            )

    def test_get_or_set_stampede_protection_lock_winner(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mock_redis.set.return_value = True  # Lock acquired

        with patch.object(self.service, "get_client", return_value=mock_redis):
            val = self.service.get_or_set(
                "heavy_feed",
                lambda: [1, 2, 3],
                local_timeout=5,
                redis_timeout=30,
                tier="core",
                stampede_protection=True,
            )
            self.assertEqual(val, [1, 2, 3])

            # Verify lock acquired and released
            mock_redis.set.assert_any_call("lock:heavy_feed", "1", nx=True, ex=5)
            mock_redis.delete.assert_called_with("lock:heavy_feed")

    def test_get_or_set_stampede_protection_lock_waiter(self):
        mock_redis = MagicMock()
        mock_redis.get.side_effect = [None, '"promised_result"']
        mock_redis.set.return_value = False  # Lock not acquired (other worker is computing)

        with patch.object(self.service, "get_client", return_value=mock_redis):
            val = self.service.get_or_set(
                "heavy_feed",
                lambda: ["unwanted_fallback"],
                local_timeout=5,
                redis_timeout=30,
                tier="core",
                stampede_protection=True,
                promise_timeout=0.2,
            )
            self.assertEqual(val, "promised_result")
            self.assertEqual(self.service.get("heavy_feed", tier="local"), "promised_result")

    @override_settings(
        REDIS_DEPLOYMENTS={
            "core": {"URL": "redis://localhost:6379/1"},
            "feeds": {"URL": "redis://localhost:6380/0"},
        }
    )
    def test_get_client_deployment_and_rw_routing(self):
        mock_core = MagicMock()
        mock_feeds = MagicMock()

        def manager_factory(**kwargs):
            mgr = MagicMock()
            if "6379" in str(kwargs.get("redis_url", "")):
                mgr.get_redis_master.return_value = mock_core
                mgr.get_redis_replica.return_value = mock_core
            else:
                mgr.get_redis_master.return_value = mock_feeds
                mgr.get_redis_replica.return_value = mock_feeds
            return mgr

        with patch("bses.cache.RedisClientManager", side_effect=manager_factory):
            service = CacheService()
            core_write = service.get_client("core", for_write=True)
            feeds_write = service.get_client("feeds", for_write=True)

            self.assertEqual(core_write, mock_core)
            self.assertEqual(feeds_write, mock_feeds)
