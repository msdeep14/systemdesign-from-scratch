from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from bses.cache import cache_service
from newsfeed.services import get_celebrity_user_ids
from photos.models import Photo
from photos.services import get_celebrity_photo_ids


class CelebrityCacheTestCase(TestCase):
    def setUp(self):
        cache_service.reset_singletons()
        self.celeb = User.objects.create_user(username="celeb_user")
        self.photo1 = Photo.objects.create(user=self.celeb, caption="Celeb Photo 1")
        self.photo2 = Photo.objects.create(user=self.celeb, caption="Celeb Photo 2")
        cache_service.delete(f"celeb_photos:{self.celeb.id}:20", tier="core")

    def tearDown(self):
        if hasattr(self, "celeb"):
            cache_service.delete(f"celeb_photos:{self.celeb.id}:20", tier="core")
        cache_service.reset_singletons()

    def test_get_celebrity_photo_ids_hits_local_cache(self):
        # Initial call hits database and populates cache
        photo_ids_first = get_celebrity_photo_ids([self.celeb.id])
        self.assertEqual(photo_ids_first, [self.photo2.id, self.photo1.id])

        # Second call must hit cache without executing Photo.objects query
        with patch.object(Photo.objects, "filter") as mock_filter:
            photo_ids_second = get_celebrity_photo_ids([self.celeb.id])
            mock_filter.assert_not_called()
            self.assertEqual(photo_ids_second, photo_ids_first)

    def test_get_celebrity_photo_ids_empty(self):
        self.assertEqual(get_celebrity_photo_ids([]), [])

    def test_get_celebrity_user_ids_uses_cache(self):
        user = User.objects.create_user(username="normal_user")
        cache_service.delete(f"celebrity_ids:{user.id}", tier="core")
        with patch(
            "newsfeed.services.get_celebrity_followed_ids", return_value=[self.celeb.id]
        ) as mock_get:
            ids_1 = get_celebrity_user_ids(user.id)
            ids_2 = get_celebrity_user_ids(user.id)
            self.assertEqual(ids_1, [self.celeb.id])
            self.assertEqual(ids_2, [self.celeb.id])
            mock_get.assert_called_once()
