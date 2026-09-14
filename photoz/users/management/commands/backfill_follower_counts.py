from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Count

from users.models import UserProfile


class Command(BaseCommand):
    help = "Backfill UserProfile.follower_count from actual Follow records"

    def handle(self, *args, **kwargs) -> None:
        """Compute follower counts from Follow table and update UserProfile."""
        self.stdout.write("Backfilling follower counts...")

        follower_counts = dict(
            User.objects.annotate(computed_count=Count("followers")).values_list(
                "id", "computed_count"
            )
        )

        batch = []
        total = 0
        for profile in UserProfile.objects.filter(user_id__in=follower_counts.keys()):
            profile.follower_count = follower_counts[profile.user_id]
            batch.append(profile)
            if len(batch) >= 5000:
                UserProfile.objects.bulk_update(batch, ["follower_count"])
                total += len(batch)
                batch = []

        if batch:
            UserProfile.objects.bulk_update(batch, ["follower_count"])
            total += len(batch)

        total_users = User.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {total} UserProfile rows out of {total_users} total User rows. "
                f"Users without a profile (bulk-created seeding accounts) are skipped."
            )
        )
