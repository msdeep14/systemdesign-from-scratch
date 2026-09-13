import uuid

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from users.models import Follow, UserProfile


class Command(BaseCommand):
    help = "Seed celebrity users and followers for Chapter 6 benchmarks"

    def handle(self, *args, **kwargs) -> None:
        """Execute the command to seed celebrity users and their followers."""
        self.stdout.write("Starting celebrity user seeding...")

        celebs_data = [("celeb_500k", 500_000), ("celeb_1m", 1_000_000), ("celeb_2m", 2_000_000)]
        max_followers = max(count for _, count in celebs_data)

        with transaction.atomic():
            celebs = self._create_celebrities(celebs_data)
            self._create_base_users(max_followers, len(celebs_data))
            base_user_ids = self._get_base_user_ids(celebs, max_followers)
            self._create_follows(celebs_data, celebs, base_user_ids)

        self.stdout.write(self.style.SUCCESS("Successfully seeded celebrity users and followers."))

    def _create_celebrities(self, celebs_data: list[tuple[str, int]]) -> dict[str, User]:
        celebs = {}
        for username, _count in celebs_data:
            user, _created = User.objects.get_or_create(username=username)
            user.set_password("password123")
            user.save()
            UserProfile.objects.get_or_create(
                user=user, defaults={"username_display": username, "first_name": username}
            )
            celebs[username] = user
            self.stdout.write(f"Celebrity {username} ready.")
        return celebs

    def _create_base_users(self, max_followers: int, num_celebs: int) -> None:
        self.stdout.write(f"Ensuring {max_followers} base users exist...")
        current_users_count = User.objects.using("default").count()
        needed_users = max_followers - current_users_count + num_celebs

        if needed_users > 0:
            self.stdout.write(
                f"Creating {needed_users} base users (this may take a few minutes)..."
            )
            batch_size = 50000
            for i in range(0, needed_users, batch_size):
                users_to_create = [
                    User(username=str(uuid.uuid4()))
                    for _ in range(min(batch_size, needed_users - i))
                ]
                User.objects.bulk_create(users_to_create, ignore_conflicts=True)
                if (i + batch_size) % 100000 == 0:
                    self.stdout.write(f"Created {i + batch_size} users...")

    def _get_base_user_ids(self, celebs: dict[str, User], max_followers: int) -> list[int]:
        self.stdout.write("Fetching base user IDs...")
        return list(
            User.objects.using("default")
            .exclude(id__in=[c.id for c in celebs.values()])
            .values_list("id", flat=True)[:max_followers]
        )

    def _create_follows(
        self, celebs_data: list[tuple[str, int]], celebs: dict[str, User], base_user_ids: list[int]
    ) -> None:
        for username, follower_count in celebs_data:
            celeb_user = celebs[username]
            existing_count = Follow.objects.using("default").filter(following=celeb_user).count()
            needed_follows = follower_count - existing_count

            if needed_follows > 0:
                self.stdout.write(f"Creating {needed_follows} follows for {username}...")
                follower_ids_to_add = base_user_ids[existing_count:follower_count]
                batch_size = 50000
                for i in range(0, len(follower_ids_to_add), batch_size):
                    follows_to_create = [
                        Follow(follower_id=fid, following=celeb_user)
                        for fid in follower_ids_to_add[i : i + batch_size]
                    ]
                    Follow.objects.bulk_create(follows_to_create, ignore_conflicts=True)
                    if (i + batch_size) % 100000 == 0:
                        self.stdout.write(f"Created {i + batch_size} follows for {username}...")
            else:
                self.stdout.write(f"{username} already has {follower_count} followers.")
