from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib import messages
from .models import Photo, Like, Comment
from .forms import PhotoUploadForm
from notifications.models import Notification
import logging

logger = logging.getLogger('bses')

@login_required
def upload_photo(request):
    community_id = request.GET.get('community')
    community = None
    if community_id:
        from communities.models import Community
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
    import json
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
