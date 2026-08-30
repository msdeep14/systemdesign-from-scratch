import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from stories.forms import StoryUploadForm
from stories.models import Story

logger = logging.getLogger("bses")


@login_required
def upload_story(request):
    if request.method == "POST":
        form = StoryUploadForm(request.POST, request.FILES)
        if form.is_valid():
            story = form.save(commit=False)
            story.user = request.user
            story.save()
            logger.info(
                "Story uploaded successfully by %s (Story ID: %s)", request.user.username, story.id
            )
            messages.success(request, "Story uploaded successfully!")
            return redirect("newsfeed")
        logger.warning("Story upload failed for %s: %s", request.user.username, form.errors)
    else:
        form = StoryUploadForm()

    return render(request, "stories/upload.html", {"form": form})


@login_required
def view_story(request, id):
    story = get_object_or_404(Story.objects.select_related("user__profile"), id=id)

    now = timezone.now()
    user_active_stories = list(
        Story.objects.filter(
            user=story.user, created_at__gte=now - timezone.timedelta(hours=24)
        ).order_by("created_at")
    )

    current_index = -1
    for i, s in enumerate(user_active_stories):
        if s.id == story.id:
            current_index = i
            break

    if current_index == -1:
        # Fallback if accessed via direct link and story expired
        user_active_stories = [story]
        current_index = 0

    next_story = (
        user_active_stories[current_index + 1]
        if current_index + 1 < len(user_active_stories)
        else None
    )
    prev_story = user_active_stories[current_index - 1] if current_index - 1 >= 0 else None

    return render(
        request,
        "stories/view.html",
        {
            "story": story,
            "next_story": next_story,
            "prev_story": prev_story,
            "user_active_stories": user_active_stories,
            "current_index": current_index,
        },
    )
