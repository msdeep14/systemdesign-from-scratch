from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Q, Count
from django.core.paginator import Paginator
from django.conf import settings
import json
from .models import Photo, Like, Comment
from .forms import PhotoUploadForm
from notifications.models import Notification
from communities.models import Community, CommunityMembership
from users.models import UserProfile, Follow
from django.core.cache import cache
import logging

logger = logging.getLogger('bses')

@login_required
def upload_photo(request):
    community_id = request.GET.get('community')
    community = None
    if community_id:
        community = get_object_or_404(Community, id=community_id)
        if not community.memberships.filter(user=request.user, status='accepted').exists():
            messages.error(request, "You must be a member to upload to this community.")
            return redirect('community_detail', id=community.id)

    if request.method == 'POST':
        form = PhotoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            photo = form.save(commit=False)
            photo.user = request.user
            if community:
                photo.community = community
            photo.save()
            
            # Redis Fan-out on write
            try:
                if hasattr(cache, 'client') and hasattr(cache.client, 'get_client'):
                    client = cache.client.get_client()
                    def add_to_feed_cache(u_id, p_id):
                        cache_key = f":1:feed:{u_id}"
                        if client.exists(cache_key):
                            if client.type(cache_key) == b'list':
                                client.lpush(cache_key, p_id)
                                client.ltrim(cache_key, 0, 999)
                            else:
                                logger.warning(f"Cache key {cache_key} is not a list. Deleting.")
                                client.delete(cache_key)
                    
                    add_to_feed_cache(request.user.id, photo.id)
                    follower_ids = Follow.objects.filter(following=request.user).values_list('follower_id', flat=True)
                    for f_id in follower_ids:
                        add_to_feed_cache(f_id, photo.id)
            except Exception as e:
                logger.error(f"Failed to update redis cache on upload: {e}")
            
            client_compressed = request.POST.get('client_compressed', 'false')
            logger.info(f"Photo uploaded successfully by {request.user.username} (Photo ID: {photo.id}, Client Compressed: {client_compressed})")
            messages.success(request, "Photo uploaded successfully!")
            if community:
                return redirect('community_detail', id=community.id)
            return redirect('profile', username=request.user.profile.username_display)
        else:
            logger.warning(f"Photo upload failed for {request.user.username}: {form.errors}")
    else:
        form = PhotoUploadForm()
        
    return render(request, 'photos/upload.html', {'form': form, 'community': community})

@login_required
def photo_detail(request, id):
    photo = get_object_or_404(
        Photo.objects.select_related('user__profile', 'community'),
        id=id
    )
    likes_count = photo.likes.count()
    has_liked = photo.likes.filter(user=request.user).exists()
    comments = photo.comments.select_related('user__profile').order_by('created_at')
    
    return render(request, 'photos/detail.html', {
        'photo': photo,
        'likes_count': likes_count,
        'has_liked': has_liked,
        'comments': comments
    })

@login_required
@require_POST
def delete_photo(request, id):
    photo = get_object_or_404(Photo, id=id)
    if photo.user != request.user:
        logger.warning(f"Unauthorized photo deletion attempt by {request.user.username} on photo {id}")
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    photo.delete()
    logger.info(f"Photo {id} deleted by {request.user.username}")
    messages.success(request, "Photo deleted.")
    return redirect('profile', username=request.user.profile.username_display)

@login_required
@require_POST
def toggle_like(request, id):
    photo = get_object_or_404(Photo, id=id)
    like_obj = Like.objects.filter(user=request.user, photo=photo).first()
    
    if like_obj:
        like_obj.delete()
        has_liked = False
        logger.info(f"User {request.user.username} unliked photo {id}")
    else:
        Like.objects.create(user=request.user, photo=photo)
        has_liked = True
        logger.info(f"User {request.user.username} liked photo {id}")
        
        # Create notification
        if photo.user != request.user:
            Notification.objects.create(
                recipient=photo.user,
                sender=request.user,
                type='photo_like',
                message=f"{request.user.profile.first_name} liked your photo.",
                photo=photo
            )
            
    likes_count = photo.likes.count()
    return JsonResponse({'has_liked': has_liked, 'likes_count': likes_count})

@login_required
@require_POST
def add_comment(request, id):
    photo = get_object_or_404(Photo, id=id)
    try:
        data = json.loads(request.body)
        text = data.get('text', '').strip()
    except:
        text = request.POST.get('text', '').strip()
    
    if not text:
        logger.warning(f"Empty comment attempt by {request.user.username} on photo {id}")
        return JsonResponse({'error': 'Comment cannot be empty'}, status=400)
        
    comment = Comment.objects.create(user=request.user, photo=photo, text=text)
    logger.info(f"Comment added by {request.user.username} on photo {id}")
    
    # Create notification
    if photo.user != request.user:
        Notification.objects.create(
            recipient=photo.user,
            sender=request.user,
            type='photo_comment',
            message=f"{request.user.profile.first_name} commented on your photo.",
            photo=photo
        )
        
    return JsonResponse({
        'id': comment.id,
        'text': comment.text,
        'user_name': request.user.profile.first_name,
        'username_display': request.user.profile.username_display,
        'created_at': comment.created_at.strftime('%Y-%m-%d %H:%M:%S')
    })


@login_required
def search_view(request):
    query = request.GET.get('q', '').strip()

    if query.startswith('#'):
        return _search_photos_by_hashtag(request, query)
    else:
        return _search_users(request, query)


def _search_users(request, query):
    results = []
    if query:
        results = UserProfile.objects.filter(
            Q(username_display__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )
    return render(request, 'photos/search_results.html', {
        'query': query,
        'search_type': 'users',
        'user_results': results,
    })


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
        my_communities = CommunityMembership.objects.filter(user=request.user, status='accepted').values_list('community', flat=True)
        if my_communities:
            visibility_q |= Q(community__in=my_communities)
        visibility_q |= Q(user=request.user)

    photos = Photo.objects.filter(
        q_objects & visibility_q
    ).select_related(
        'user__profile', 'community'
    ).order_by('-created_at')

    paginator = Paginator(photos, getattr(settings, 'BSES_PAGE_SIZE', 20))
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    photo_ids = [p.id for p in page_obj.object_list]
    
    # Decoupled aggregations: We query likes and comments separately for the 
    # photos on the current page to avoid generating massive, slow SQL JOINs 
    # (a Cartesian product) that occur when using multiple .annotate() calls 
    # on the main Photo query.
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

    liked_photo_ids = set(
        request.user.like_set.filter(photo_id__in=photo_ids).values_list('photo_id', flat=True)
    )

    return render(request, 'photos/search_results.html', {
        'query': query,
        'search_type': 'photos',
        'page_obj': page_obj,
        'liked_photo_ids': liked_photo_ids,
    })
