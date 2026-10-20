from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from photos.models import Like, Photo
from photos.services import bulk_record_likes, is_photo_liked_by_user, toggle_photo_like_redis


class LikesScalabilityTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser1")
        self.uploader = User.objects.create_user(username="uploader1")
        self.photo = Photo.objects.create(user=self.uploader, caption="Test Photo", likes_count=10)

    def test_is_photo_liked_uses_user_centric_cache_on_cache_hit(self):
        mock_redis = MagicMock()
        user_key = f"user:{self.user.id}:liked_photos"
        mock_redis.exists.return_value = True
        mock_redis.sismember.return_value = True

        with patch("photos.services.redis_client", mock_redis):
            liked = is_photo_liked_by_user(self.photo.id, self.user.id)

        self.assertTrue(liked)
        mock_redis.exists.assert_called_with(user_key)
        mock_redis.sismember.assert_called_with(user_key, str(self.photo.id))
        for call in mock_redis.sadd.call_args_list:
            args, _ = call
            self.assertFalse(str(args[0]).endswith(":likers"))

    def test_is_photo_liked_hydrates_user_centric_cache_on_miss(self):
        Like.objects.create(user=self.user, photo=self.photo)

        mock_redis = MagicMock()
        mock_redis.exists.return_value = False

        with patch("photos.services.redis_client", mock_redis):
            liked = is_photo_liked_by_user(self.photo.id, self.user.id)

        self.assertTrue(liked)
        user_key = f"user:{self.user.id}:liked_photos"
        mock_redis.sadd.assert_any_call(user_key, str(self.photo.id))
        mock_redis.expire.assert_called_with(user_key, 86400)
        # Verify no photo likers set was created
        for call in mock_redis.sadd.call_args_list:
            args, _ = call
            self.assertFalse(str(args[0]).endswith(":likers"))

    def test_toggle_like_updates_user_centric_cache_and_counter(self):
        mock_redis = MagicMock()
        mock_redis.exists.return_value = True
        user_key = f"user:{self.user.id}:liked_photos"
        count_key = f"photo:{self.photo.id}:likes_count"

        # Simulate user liking the photo
        mock_redis.sismember.return_value = False
        mock_redis.incr.return_value = 11

        with patch("photos.services.redis_client", mock_redis):
            has_liked, new_count = toggle_photo_like_redis(
                self.photo.id, self.user.id, self.photo.likes_count
            )

        self.assertTrue(has_liked)
        self.assertEqual(new_count, 11)
        mock_redis.sadd.assert_any_call(user_key, str(self.photo.id))
        mock_redis.incr.assert_called_with(count_key)
        for call in mock_redis.sadd.call_args_list:
            args, _ = call
            self.assertFalse(str(args[0]).endswith(":likers"))

    def test_bulk_record_likes_does_not_add_to_photo_likers_set(self):
        mock_redis = MagicMock()
        mock_redis.exists.return_value = False

        with patch("photos.services.redis_client", mock_redis):
            recorded = bulk_record_likes([(self.photo.id, self.user.id)])

        self.assertEqual(recorded, 1)
        for call in mock_redis.sadd.call_args_list:
            args, _ = call
            self.assertFalse(str(args[0]).endswith(":likers"))
