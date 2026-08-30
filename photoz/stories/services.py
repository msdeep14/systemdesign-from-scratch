from collections import defaultdict

from django.utils import timezone

from stories.models import Story


def get_active_stories_for_users(user_ids):
    """
    Returns a dictionary of active stories grouped by user.
    Keys are user objects, values are lists of active Story objects.
    Only returns users who have at least one active story.
    """
    now = timezone.now()
    # ARCHITECTURE DECISION: "Pull on Read" over Redis "Fan-Out on Write"
    # Why?
    # 1. Ephemeral Content: Fanning out writes to thousands of followers' Redis lists for content
    #    that disappears in 24 hours creates high write amplification and
    #    complex cron eviction logic.
    # 2. Performance: A Postgres composite index on (user_id, created_at)
    #    executes this query in <5ms,
    #    even for users following thousands of accounts, by scanning only a tiny 24-hour time slice.
    #
    # We select_related the user profile because these stories are passed directly to the UI.
    stories_qs = (
        Story.objects.filter(
            user_id__in=user_ids, created_at__gte=now - timezone.timedelta(hours=24)
        )
        .select_related("user__profile")
        .order_by("created_at")
    )

    grouped_stories = defaultdict(list)
    for story in stories_qs:
        grouped_stories[story.user].append(story)

    return dict(grouped_stories)
