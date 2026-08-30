from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Story(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stories"
    )
    image = models.ImageField(upload_to="stories/")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(editable=False)

    def save(self, *args, **kwargs):
        if not self.id and not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        return timezone.now() < self.expires_at

    class Meta:
        verbose_name_plural = "Stories"
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"Story by {self.user.username} at {self.created_at}"
