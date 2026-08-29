from django.shortcuts import get_object_or_404

from communities.models import Community, CommunityMembership


def get_community_by_id(community_id):
    """Fetches a community by its ID."""
    return get_object_or_404(Community, id=community_id)


def get_accepted_community_ids(user):
    """Returns a list of community IDs where the user has an accepted membership."""
    return list(
        CommunityMembership.objects.filter(user=user, status="accepted").values_list(
            "community", flat=True
        )
    )


def is_user_member_of_community(user, community_id):
    """Checks if a user is an accepted member of a specific community."""
    return CommunityMembership.objects.filter(
        community_id=community_id, user=user, status="accepted"
    ).exists()
