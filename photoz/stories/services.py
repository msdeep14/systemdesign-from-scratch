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
    # Pull active stories for the given user ids
    # Because we're passing these to the UI, we select_related the user profile
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
