from django.apps import AppConfig


class NewsfeedConfig(AppConfig):  # drift:ignore
    default_auto_field = "django.db.models.BigAutoField"
    name = "newsfeed"

    def ready(self):  # drift:ignore
        import newsfeed.signals  # pylint: disable=import-outside-toplevel  # noqa: F401
