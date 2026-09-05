from django.db.models import Q

from photos.models import Photo


def get_feed_photo_ids(user_id, followed_user_ids, community_ids):
    """
    Fetches the top 1000 photo IDs for a user's feed based on followed users and communities.
    """
    feed_qs = (
        Photo.objects.filter(
            Q(user_id__in=followed_user_ids, community__isnull=True)
            | Q(community_id__in=community_ids)
            | Q(user_id=user_id)
        )
        .order_by("-created_at")
        .distinct()[:1000]
    )
    return list(feed_qs.values_list("id", flat=True))


def get_photos_by_ids(photo_ids):
    """
    Returns a list of Photo objects for the given IDs, preserving the order of the IDs.
    """
    photos_qs = Photo.objects.filter(id__in=photo_ids).select_related("user__profile", "community")
    photos_dict = {p.id: p for p in photos_qs}
    return [photos_dict[pid] for pid in photo_ids if pid in photos_dict]
