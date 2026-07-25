from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.conf import settings
from django.db.models import Count, Q
from photos.models import Photo, Like, Comment
from users.models import Follow
from communities.models import CommunityMembership

from django.core.cache import cache

@login_required
def newsfeed(request):
    cache_key = f"feed:{request.user.id}"
    photo_ids = cache.get(cache_key)
    
    if photo_ids is None:
        followed_users = Follow.objects.filter(follower=request.user).values_list('following', flat=True)
        my_communities = CommunityMembership.objects.filter(user=request.user, status='accepted').values_list('community', flat=True)
        
        feed_qs = Photo.objects.filter(
            Q(user__in=followed_users, community__isnull=True) |
            Q(community__in=my_communities) |
            Q(user=request.user)
        ).order_by('-created_at').distinct()[:1000]
        
        photo_ids = list(feed_qs.values_list('id', flat=True))
        cache.set(cache_key, photo_ids, timeout=3600)
    
    paginator = Paginator(photo_ids, getattr(settings, 'BSES_PAGE_SIZE', 20))
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    page_photo_ids = page_obj.object_list
    photos_qs = Photo.objects.filter(id__in=page_photo_ids).select_related('user__profile', 'community')
    photos_dict = {p.id: p for p in photos_qs}
    page_photos = [photos_dict[pid] for pid in page_photo_ids if pid in photos_dict]
    page_obj.object_list = page_photos
    
    photo_ids = page_photo_ids
    likes_counts = dict(
        Like.objects.filter(photo_id__in=photo_ids)
        .values('photo_id')
        .annotate(count=Count('id'))
        .values_list('photo_id', 'count')
    )
    comments_counts = dict(
        Comment.objects.filter(photo_id__in=photo_ids)
        .values('photo_id')
        .annotate(count=Count('id'))
        .values_list('photo_id', 'count')
    )
    for photo in page_obj.object_list:
        photo.likes_count = likes_counts.get(photo.id, 0)
        photo.comments_count = comments_counts.get(photo.id, 0)
    
    liked_photo_ids = set(request.user.like_set.values_list('photo_id', flat=True)) if request.user.is_authenticated else set()
    
    context = {
        'page_obj': page_obj,
        'liked_photo_ids': liked_photo_ids,
    }
    
    return render(request, 'newsfeed/feed.html', context)
