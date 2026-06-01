from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth.models import User
from .models import Community, CommunityMembership
from .forms import CommunityForm
from notifications.models import Notification
import logging

logger = logging.getLogger('bses')

@login_required
def list_communities(request):
    memberships = CommunityMembership.objects.filter(user=request.user, status='accepted').select_related('community')
    my_communities = [m.community for m in memberships]
    created_communities = list(Community.objects.filter(creator=request.user))
    
    # Combine uniquely by id
    communities_dict = {c.id: c for c in my_communities + created_communities}
    communities = list(communities_dict.values())
    
    return render(request, 'communities/list.html', {'communities': communities})

@login_required
def create_community(request):
    if request.method == 'POST':
        form = CommunityForm(request.POST)
        if form.is_valid():
            community = form.save(commit=False)
            community.creator = request.user
            community.save()
            
            CommunityMembership.objects.create(
                community=community,
                user=request.user,
                role='creator',
                status='accepted'
            )
            
            logger.info(f"Community '{community.name}' created successfully by {request.user.username}")
            messages.success(request, f"Community '{community.name}' created successfully!")
            return redirect('community_detail', id=community.id)
        else:
            logger.warning(f"Community creation failed for {request.user.username}: {form.errors}")
    else:
        form = CommunityForm()
        
    return render(request, 'communities/create.html', {'form': form})

@login_required
def community_detail(request, id):
    community = get_object_or_404(Community, id=id)
    
    is_member = community.memberships.filter(user=request.user, status='accepted').exists()
    
    if not is_member:
        logger.warning(f"Unauthorized access attempt to community {community.id} by {request.user.username}")
        messages.error(request, "You are not a member of this community.")
        return redirect('list_communities')
        
    members = community.memberships.filter(status='accepted').select_related('user__profile')
    photos = community.photo_set.all().order_by('-created_at')
    
    return render(request, 'communities/detail.html', {
        'community': community,
        'members': members,
        'photos': photos
    })

@login_required
@require_POST
def invite_member(request, id):
    community = get_object_or_404(Community, id=id)
    username = request.POST.get('username')
    
    if not community.memberships.filter(user=request.user, status='accepted').exists():
        logger.warning(f"Unauthorized invite attempt in community {community.id} by {request.user.username}")
        messages.error(request, "Only members can invite others.")
        return redirect('community_detail', id=community.id)
        
    from users.models import UserProfile
    profile = UserProfile.objects.filter(username_display=username).first()
    
    if not profile:
        logger.warning(f"Invite failed: User '{username}' not found by {request.user.username}")
        messages.error(request, "User not found.")
        return redirect('community_detail', id=community.id)
        
    target_user = profile.user
    
    if target_user == request.user:
        logger.warning(f"Invite failed: {request.user.username} tried to invite themselves")
        messages.error(request, "You cannot invite yourself.")
        return redirect('community_detail', id=community.id)
        
    existing = CommunityMembership.objects.filter(community=community, user=target_user).first()
    if existing:
        if existing.status == 'accepted':
            messages.error(request, f"{profile.username_display} is already a member.")
        elif existing.status == 'pending':
            messages.info(request, f"An invitation is already pending for {profile.username_display}.")
        else:
            existing.status = 'pending'
            existing.save()
            messages.success(request, f"Invitation re-sent to {profile.username_display}.")
    else:
        membership = CommunityMembership.objects.create(
            community=community,
            user=target_user,
            role='member',
            status='pending'
        )
        
        Notification.objects.create(
            recipient=target_user,
            sender=request.user,
            type='community_invite',
            message=f"{request.user.profile.first_name} invited you to join '{community.name}'.",
            membership=membership
        )
        logger.info(f"Invitation to community {community.id} sent to {target_user.username} by {request.user.username}")
        messages.success(request, f"Invitation sent to {profile.username_display}.")
        
    return redirect('community_detail', id=community.id)

@login_required
@require_POST
def respond_invitation(request, id):
    membership = get_object_or_404(CommunityMembership, id=id, user=request.user)
    action = request.POST.get('action')
    
    if action == 'accept':
        membership.status = 'accepted'
        membership.save()
        logger.info(f"User {request.user.username} accepted invitation to community {membership.community.id}")
        messages.success(request, f"You have joined {membership.community.name}!")
        return redirect('community_detail', id=membership.community.id)
    elif action == 'reject':
        membership.status = 'rejected'
        membership.save()
        logger.info(f"User {request.user.username} rejected invitation to community {membership.community.id}")
        messages.success(request, f"You rejected the invitation to {membership.community.name}.")
        return redirect('notification_list')
        
    return redirect('notification_list')
