from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from .models import UserProfile, Follow
from .forms import UserRegistrationForm, UserProfileEditForm
from django.views.decorators.http import require_POST
from django.contrib.auth.forms import AuthenticationForm
import uuid
import logging
from django.core.cache import cache

logger = logging.getLogger('bses')

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('newsfeed')
        
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            username_display = form.cleaned_data.get('username_display')
            # Generate a unique username for django auth user
            django_username = str(uuid.uuid4())[:30]
            user = User.objects.create_user(
                username=django_username,
                password=form.cleaned_data.get('password'),
                first_name=form.cleaned_data.get('first_name'),
                last_name=form.cleaned_data.get('last_name')
            )
            # Create user profile
            UserProfile.objects.create(
                user=user,
                username_display=username_display,
                first_name=form.cleaned_data.get('first_name'),
                last_name=form.cleaned_data.get('last_name')
            )
            login(request, user)
            logger.info(f"User signed up successfully: {username_display}")
            messages.success(request, f"Welcome, {username_display}!")
            return redirect('newsfeed')
        else:
            logger.warning(f"Signup form invalid: {form.errors}")
    else:
        form = UserRegistrationForm()
    
    return render(request, 'users/signup.html', {'form': form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('newsfeed')
        
    if request.method == 'POST':
        # We need to authenticate using the username_display instead of django's username
        username_display = request.POST.get('username')
        password = request.POST.get('password')
        try:
            profile = UserProfile.objects.get(username_display=username_display)
            user = authenticate(request, username=profile.user.username, password=password)
            if user is not None:
                login(request, user)
                logger.info(f"User logged in successfully: {username_display}")
                return redirect('newsfeed')
            else:
                logger.warning(f"Invalid login attempt for username: {username_display}")
                messages.error(request, "Invalid username or password.")
        except UserProfile.DoesNotExist:
            logger.warning(f"Login attempt for non-existent username: {username_display}")
            messages.error(request, "Invalid username or password.")
            
    return render(request, 'users/login.html')

def logout_view(request):
    logger.info(f"User logged out: {request.user.username}")
    logout(request)
    return redirect('login')

def profile_view(request, username):
    profile = get_object_or_404(
        UserProfile.objects.select_related('user'),
        username_display=username
    )
    user_obj = profile.user
    
    photos = user_obj.photos.filter(community__isnull=True).order_by('-created_at') if hasattr(user_obj, 'photos') else []
    
    followers_count = user_obj.followers.count()
    following_count = user_obj.following.count()
    
    is_following = False
    if request.user.is_authenticated and request.user != user_obj:
        is_following = Follow.objects.filter(follower=request.user, following=user_obj).exists()
        
    context = {
        'profile': profile,
        'photos': photos,
        'followers_count': followers_count,
        'following_count': following_count,
        'is_following': is_following,
    }
    return render(request, 'users/profile.html', context)

@login_required
def edit_profile_view(request, username):
    profile = get_object_or_404(UserProfile, username_display=username)
    
    if request.user != profile.user:
        logger.warning(f"Unauthorized profile edit attempt by {request.user.username} on profile {username}")
        messages.error(request, "You can only edit your own profile.")
        return redirect('profile', username=username)
        
    if request.method == 'POST':
        form = UserProfileEditForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            request.user.first_name = form.cleaned_data.get('first_name')
            request.user.last_name = form.cleaned_data.get('last_name')
            request.user.save()
            logger.info(f"Profile updated successfully: {username}")
            messages.success(request, "Profile updated successfully.")
            return redirect('profile', username=username)
        else:
            logger.warning(f"Profile edit form invalid for {username}: {form.errors}")
    else:
        form = UserProfileEditForm(instance=profile)
        
    return render(request, 'users/edit_profile.html', {'form': form, 'profile': profile})

@login_required
@require_POST
def delete_account_view(request, username):
    profile = get_object_or_404(UserProfile, username_display=username)
    
    if request.user != profile.user:
        logger.warning(f"Unauthorized account delete attempt by {request.user.username} on {username}")
        messages.error(request, "Unauthorized")
        return redirect('profile', username=username)
        
    user = request.user
    logger.info(f"Account deleted: {username}")
    logout(request)
    follower_ids = list(user.followers.values_list('follower_id', flat=True))
    for f_id in follower_ids:
        cache.delete(f"feed:{f_id}")
    cache.delete(f"feed:{user.id}")
    
    user.delete()
    messages.success(request, "Your account has been deleted.")
    return redirect('login')

@login_required
@require_POST
def toggle_follow_view(request, username):
    profile = get_object_or_404(UserProfile, username_display=username)
    target_user = profile.user
    
    if request.user == target_user:
        return JsonResponse({'error': 'Cannot follow yourself'}, status=400)
        
    follow_obj = Follow.objects.filter(follower=request.user, following=target_user).first()
    
    if follow_obj:
        follow_obj.delete()
        is_following = False
        logger.info(f"User {request.user.username} unfollowed {target_user.username}")
    else:
        Follow.objects.create(follower=request.user, following=target_user)
        is_following = True
        logger.info(f"User {request.user.username} followed {target_user.username}")
        
    cache.delete(f"feed:{request.user.id}")
        
    followers_count = target_user.followers.count()
    
    return JsonResponse({
        'is_following': is_following,
        'followers_count': followers_count
    })
