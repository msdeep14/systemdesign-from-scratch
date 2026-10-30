from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from bses.cache import cache_service
from newsfeed.services import (
    get_cached_feed,
    invalidate_feed_cache,
    push_to_feed_cache,
    push_to_feed_cache_bulk,
)


class FeedsRedisRoutingTestCase(TestCase):
    def setUp(self):
        cache_service.reset_singletons()
        self.user = User.objects.create_user(username="feed_routing_user")
        self.follower = User.objects.create_user(username="feed_routing_follower")

    def tearDown(self):
        cache_service.reset_singletons()

    def test_feed_push_routes_to_feeds_deployment(self):
        mock_feeds_client = MagicMock()
        mock_feeds_client.exists.return_value = True
        mock_feeds_client.type.return_value = b"list"
        mock_core_client = MagicMock()

        def client_router(deployment="core", for_write=False):
            if deployment == "feeds":
                return mock_feeds_client
            return mock_core_client

        with patch.object(cache_service, "get_client", side_effect=client_router):
            push_to_feed_cache(self.user.id, 101)

            mock_feeds_client.lpush.assert_called_once_with(f":1:feed:{self.user.id}", 101)
            mock_feeds_client.ltrim.assert_called_once_with(f":1:feed:{self.user.id}", 0, 999)
            mock_core_client.lpush.assert_not_called()

    def test_feed_bulk_push_routes_to_feeds_deployment(self):
        mock_feeds_client = MagicMock()
        mock_pipeline = MagicMock()
        mock_feeds_client.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.side_effect = [[True], []]
        mock_core_client = MagicMock()

        def client_router(deployment="core", for_write=False):
            if deployment == "feeds":
                return mock_feeds_client
            return mock_core_client

        with patch.object(cache_service, "get_client", side_effect=client_router):
            push_to_feed_cache_bulk([self.follower.id], 202)

            mock_pipeline.lpush.assert_called_once_with(f":1:feed:{self.follower.id}", 202)
            mock_pipeline.ltrim.assert_called_once_with(f":1:feed:{self.follower.id}", 0, 999)
            mock_core_client.pipeline.assert_not_called()

    def test_get_cached_feed_reads_from_feeds_deployment(self):
        mock_feeds_read_client = MagicMock()
        mock_feeds_read_client.type.return_value = b"list"
        mock_feeds_read_client.lrange.return_value = [b"303", b"304"]
        mock_core_client = MagicMock()
        mock_core_client.get.return_value = None

        def client_router(deployment="core", for_write=False):
            if deployment == "feeds":
                return mock_feeds_read_client
            return mock_core_client

        with (
            patch.object(cache_service, "get_client", side_effect=client_router),
            patch("newsfeed.services.get_celebrity_user_ids", return_value=[]),
        ):
            feed = get_cached_feed(self.user.id)

            self.assertEqual(feed, [303, 304])
            mock_feeds_read_client.lrange.assert_called_once_with(f":1:feed:{self.user.id}", 0, -1)
            mock_core_client.lrange.assert_not_called()

    def test_invalidate_feed_cache_deletes_from_feeds_deployment(self):
        mock_feeds_write_client = MagicMock()
        mock_core_client = MagicMock()

        def client_router(deployment="core", for_write=False):
            if deployment == "feeds":
                return mock_feeds_write_client
            return mock_core_client

        with patch.object(cache_service, "get_client", side_effect=client_router):
            invalidate_feed_cache(self.user.id)

            mock_feeds_write_client.delete.assert_called_once_with(f":1:feed:{self.user.id}")
            mock_core_client.delete.assert_not_called()
