from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Count

from users.models import UserProfile

BATCH_SIZE = 5000


class Command(BaseCommand):
    help = "Backfill UserProfile.follower_count from actual Follow records"

    def handle(self, *args, **kwargs) -> None:
        self.stdout.write("Backfilling follower counts...")
        total = 0
        batch = []

        for profile in UserProfile.objects.only("user_id", "follower_count").iterator(
            chunk_size=BATCH_SIZE
        ):
            batch.append(profile)
            if len(batch) >= BATCH_SIZE:
                total += self._update_batch(batch)
                batch = []

        if batch:
            total += self._update_batch(batch)

        self.stdout.write(self.style.SUCCESS(f"Updated {total} UserProfile rows."))

    def _update_batch(self, profiles):
        user_ids = [p.user_id for p in profiles]
        counts = dict(
            User.objects.filter(id__in=user_ids)
            .annotate(computed_count=Count("followers"))
            .values_list("id", "computed_count")
        )
        for profile in profiles:
            profile.follower_count = counts.get(profile.user_id, 0)
        UserProfile.objects.bulk_update(profiles, ["follower_count"])
        return len(profiles)
