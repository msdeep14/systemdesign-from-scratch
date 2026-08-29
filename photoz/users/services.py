from django.db.models import Q

from users.models import Follow, UserProfile


def get_followed_user_ids(user):
    """Returns a list of IDs of users that the given user follows."""
    return list(Follow.objects.filter(follower=user).values_list("following", flat=True))


def get_follower_user_ids(user):
    """Returns a list of IDs of users that follow the given user."""
    return list(Follow.objects.filter(following=user).values_list("follower_id", flat=True))


def search_users(query):
    """Searches for users by username or name."""
    if not query:
        return []
    return list(
        UserProfile.objects.filter(
            Q(username_display__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    )


def get_user_profile_by_username(username):
    """Fetches a UserProfile by username display."""
    return UserProfile.objects.filter(username_display=username).first()
