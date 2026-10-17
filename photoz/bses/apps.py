"""Application configuration for bses core services."""

from django.apps import AppConfig


class BsesConfig(AppConfig):
    """Configuration for bses application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "bses"
