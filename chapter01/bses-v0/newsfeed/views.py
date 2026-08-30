from communities.models import CommunityMembership
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from photos.models import Photo
from users.models import Follow


@login_required
def newsfeed(request):
    followed_users = Follow.objects.filter(follower=request.user).values_list(
        "following", flat=True
    )
    my_communities = CommunityMembership.objects.filter(
        user=request.user, status="accepted"
    ).values_list("community", flat=True)

    feed = (
        Photo.objects.filter(
            Q(user__in=followed_users, community__isnull=True)
            | Q(community__in=my_communities)
            | Q(user=request.user)
        )
        .order_by("-created_at")
        .distinct()
    )

    paginator = Paginator(feed, getattr(settings, "BSES_PAGE_SIZE", 20))
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    liked_photo_ids = (
        set(request.user.like_set.values_list("photo_id", flat=True))
        if request.user.is_authenticated
        else set()
    )

    context = {
        "page_obj": page_obj,
        "liked_photo_ids": liked_photo_ids,
    }

    return render(request, "newsfeed/feed.html", context)
