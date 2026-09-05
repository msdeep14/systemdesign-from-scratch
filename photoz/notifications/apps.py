from django.apps import AppConfig


class NotificationsConfig(AppConfig):  # drift:ignore
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"

    def ready(self):  # drift:ignore
        import notifications.signals  # pylint: disable=import-outside-toplevel  # noqa: F401
