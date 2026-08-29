import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control

from newsfeed.services import get_cached_feed
from photos.services import get_photos_by_ids

logger = logging.getLogger("bses")


@cache_control(private=True, max_age=60, stale_if_error=86400)
@login_required
def newsfeed(request):
    # Delegate caching, locking, and fetching to the service layer
    photo_ids = get_cached_feed(request.user.id)

    if photo_ids is None:
        return HttpResponse(
            "Feed is currently generating. Please try again in a moment.", status=503
        )

    paginator = Paginator(photo_ids, getattr(settings, "BSES_PAGE_SIZE", 20))
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Delegate object fetching to the photos service layer
    page_obj.object_list = get_photos_by_ids(page_obj.object_list)

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
