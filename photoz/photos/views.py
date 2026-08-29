import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from communities.services import (
    get_accepted_community_ids,
    get_community_by_id,
    is_user_member_of_community,
)
from photos.cdn import invalidate_cache
from photos.forms import PhotoUploadForm
from photos.models import Comment, Like, Photo
from photos.signals import photo_commented, photo_deleted, photo_liked, photo_uploaded
from users.services import search_users

logger = logging.getLogger("bses")


@login_required
def upload_photo(request):
    community_id = request.GET.get("community")
    community = None
    if community_id:
        community = get_community_by_id(community_id)
        if not is_user_member_of_community(request.user, community.id):
            messages.error(request, "You must be a member to upload to this community.")
            return redirect("community_detail", id=community.id)

    if request.method == "POST":
        form = PhotoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            photo = form.save(commit=False)
            photo.user = request.user
            if community:
                photo.community = community
            photo.save()

            # Emit signal for decoupling components
            photo_uploaded.send(sender=Photo, photo=photo)

            client_compressed = request.POST.get("client_compressed", "false")
            logger.info(
                "Photo uploaded successfully by %s (Photo ID: %s, Client Compressed: %s)",
                request.user.username,
                photo.id,
                client_compressed,
            )
            messages.success(request, "Photo uploaded successfully!")
            if community:
                return redirect("community_detail", id=community.id)
            return redirect("profile", username=request.user.profile.username_display)

        logger.warning("Photo upload failed for %s: %s", request.user.username, form.errors)
    else:
        form = PhotoUploadForm()

    return render(request, "photos/upload.html", {"form": form, "community": community})


@login_required
def photo_detail(request, id):
    photo = get_object_or_404(Photo.objects.select_related("user__profile", "community"), id=id)
    has_liked = photo.likes.filter(user=request.user).exists()
    comments = photo.comments.select_related("user__profile").order_by("created_at")

    return render(
        request,
        "photos/detail.html",
        {
            "photo": photo,
            "likes_count": photo.likes_count,
            "comments_count": photo.comments_count,
            "has_liked": has_liked,
            "comments": comments,
        },
    )


@login_required
@require_POST
def delete_photo(request, id):
    photo = get_object_or_404(Photo, id=id)
    if photo.user != request.user:
        logger.warning(
            "Unauthorized photo deletion attempt by %s on photo %s", request.user.username, id
        )
        return JsonResponse({"error": "Unauthorized"}, status=403)

    image_path = photo.image.name

    # Delete from DB first, then invalidate cache.
    photo.delete()
    invalidate_cache(image_path)

    # Emit deletion signal
    photo_deleted.send(sender=Photo, user=request.user)

    logger.info("Photo %s deleted by %s", id, request.user.username)
    messages.success(request, "Photo deleted.")
    return redirect("profile", username=request.user.profile.username_display)


@login_required
@require_POST
def toggle_like(request, id):
    photo = get_object_or_404(Photo, id=id)
    like_obj = Like.objects.filter(user=request.user, photo=photo).first()

    if like_obj:
        like_obj.delete()
        Photo.objects.filter(id=photo.id).update(likes_count=F("likes_count") - 1)
        has_liked = False
        logger.info("User %s unliked photo %s", request.user.username, id)
    else:
        Like.objects.create(user=request.user, photo=photo)
        Photo.objects.filter(id=photo.id).update(likes_count=F("likes_count") + 1)
        has_liked = True
        logger.info("User %s liked photo %s", request.user.username, id)

        # Emit signal for decoupling components
        if photo.user != request.user:
            photo_liked.send(sender=Like, photo=photo, liker=request.user)

    photo.refresh_from_db(fields=["likes_count"])
    return JsonResponse({"has_liked": has_liked, "likes_count": photo.likes_count})


@login_required
@require_POST
def add_comment(request, id):
    photo = get_object_or_404(Photo, id=id)
    try:
        data = json.loads(request.body)
        text = data.get("text", "").strip()
    except (json.JSONDecodeError, KeyError):
        text = request.POST.get("text", "").strip()

    if not text:
        logger.warning("Empty comment attempt by %s on photo %s", request.user.username, id)
        return JsonResponse({"error": "Comment cannot be empty"}, status=400)

    comment = Comment.objects.create(user=request.user, photo=photo, text=text)
    Photo.objects.filter(id=photo.id).update(comments_count=F("comments_count") + 1)
    logger.info("Comment added by %s on photo %s", request.user.username, id)

    # Emit signal for decoupling components
    if photo.user != request.user:
        photo_commented.send(sender=Comment, photo=photo, commenter=request.user)

    return JsonResponse(
        {
            "id": comment.id,
            "text": comment.text,
            "user_name": request.user.profile.first_name,
            "username_display": request.user.profile.username_display,
            "created_at": comment.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


@login_required
def search_view(request):
    query = request.GET.get("q", "").strip()

    if query.startswith("#"):
        return _search_photos_by_hashtag(request, query)
    return _search_users(request, query)


def _search_users(request, query):
    results = search_users(query)
    return render(
        request,
        "photos/search_results.html",
        {
            "query": query,
            "search_type": "users",
            "user_results": results,
        },
    )


def _search_photos_by_hashtag(request, query):
    # Support multiple hashtags like "#sunset #nature"
    parts = query.split()
    q_objects = Q()
    for part in parts:
        q_objects &= Q(caption__icontains=part)

    # Enforce privacy: users should only see public photos (no community)
    # OR photos from communities they are a member of, OR their own photos.
    visibility_q = Q(community__isnull=True)
    if request.user.is_authenticated:
        my_communities = get_accepted_community_ids(request.user)
        if my_communities:
            visibility_q |= Q(community__in=my_communities)
        visibility_q |= Q(user=request.user)

    photos = (
        Photo.objects.filter(q_objects & visibility_q)
        .select_related("user__profile", "community")
        .order_by("-created_at")
    )

    paginator = Paginator(photos, getattr(settings, "BSES_PAGE_SIZE", 20))
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    photo_ids = [p.id for p in page_obj.object_list]

    liked_photo_ids = set(
        request.user.like_set.filter(photo_id__in=photo_ids).values_list("photo_id", flat=True)
    )

    return render(
        request,
        "photos/search_results.html",
        {
            "query": query,
            "search_type": "photos",
            "page_obj": page_obj,
            "liked_photo_ids": liked_photo_ids,
        },
    )
