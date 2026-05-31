from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.conf import settings
from .models import Notification
import logging

logger = logging.getLogger('bses')

@login_required
def notification_list(request):
    notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    
    paginator = Paginator(notifications, getattr(settings, 'BSES_PAGE_SIZE', 20))
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'notifications/list.html', {'page_obj': page_obj})

@login_required
@require_POST
def mark_read(request, id):
    notification = get_object_or_404(Notification, id=id, recipient=request.user)
    notification.is_read = True
    notification.save()
    logger.info(f"User {request.user.username} marked notification {id} as read")
    return JsonResponse({'status': 'ok'})

@login_required
@require_POST
def mark_all_read(request):
    count = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    logger.info(f"User {request.user.username} marked all {count} notifications as read")
    return JsonResponse({'status': 'ok'})
