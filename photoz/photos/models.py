from django.db import models
from django.contrib.auth.models import User
from django.contrib.postgres.indexes import GinIndex
from .utils import photo_upload_path

class Photo(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='photos')
    community = models.ForeignKey('communities.Community', on_delete=models.SET_NULL, null=True, blank=True)
    image = models.ImageField(upload_to=photo_upload_path)
    caption = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['user', '-created_at'], name='idx_photo_user_created'),
            models.Index(fields=['community', '-created_at'], name='idx_photo_community_created'),
            GinIndex(name='idx_photo_caption_trgm', fields=['caption'], opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return f"Photo {self.id} by {self.user.username}"

class Like(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'photo'], name='unique_like')
        ]

class Comment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['photo', 'created_at'], name='idx_comment_photo_created'),
        ]

