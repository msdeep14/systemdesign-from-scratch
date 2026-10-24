from unittest.mock import MagicMock, patch

from django.test import TestCase

from newsfeed.services import _get_feed_from_redis, _save_feed_to_redis
from photos.services import get_photo_likes_count, update_like_count_redis
from users.services import get_follower_count, increment_follower_count_redis


class RedisRoutingTestCase(TestCase):
    def test_photos_read_uses_replica_and_write_uses_master(self):
        mock_master = MagicMock()
        mock_replica = MagicMock()

        with (
            patch("photos.services.get_redis_master", return_value=mock_master),
            patch("photos.services.get_redis_replica", return_value=mock_replica),
        ):
            mock_replica.get.return_value = "42"
            count = get_photo_likes_count(photo_id=1, db_likes_count=10)
            self.assertEqual(count, 42)
            mock_replica.get.assert_called_with("photo:1:likes_count")

            update_like_count_redis(photo_id=1, db_likes_count=10, increment=True)
            mock_master.incr.assert_called_with("photo:1:likes_count")

    def test_newsfeed_read_uses_replica_and_write_uses_master(self):
        mock_master = MagicMock()
        mock_replica = MagicMock()

        with (
            patch("newsfeed.services.get_redis_master", return_value=mock_master),
            patch("newsfeed.services.get_redis_replica", return_value=mock_replica),
        ):
            mock_replica.type.return_value = b"list"
            mock_replica.lrange.return_value = ["101", "102"]
            feed = _get_feed_from_redis(mock_replica, ":1:feed:1")
            self.assertEqual(feed, [101, 102])

            _save_feed_to_redis(mock_master, ":1:feed:1", [101, 102])
            mock_master.rpush.assert_called_with(":1:feed:1", 101, 102)

    def test_users_read_uses_replica_and_write_uses_master(self):
        mock_master = MagicMock()
        mock_replica = MagicMock()

        with (
            patch("users.services.get_redis_master", return_value=mock_master),
            patch("users.services.get_redis_replica", return_value=mock_replica),
        ):
            mock_replica.get.return_value = "5"
            count = get_follower_count(user_id=1, db_follower_count=10)
            self.assertEqual(count, 15)
            mock_replica.get.assert_called_with("user:1:follower_count")

            increment_follower_count_redis(user_id=1)
            mock_master.incr.assert_called_with("user:1:follower_count")
