from django.db import models
from django.contrib.auth.models import User

class Notification(models.Model):
    TYPE_CHOICES = (
        ('community_invite', 'Community Invite'),
        ('photo_like', 'Photo Like'),
        ('photo_comment', 'Photo Comment'),
    )
    
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_notifications', null=True, blank=True)
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    message = models.TextField()
    photo = models.ForeignKey('photos.Photo', on_delete=models.SET_NULL, null=True, blank=True)
    membership = models.ForeignKey('communities.CommunityMembership', on_delete=models.SET_NULL, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.type} for {self.recipient.username}"
