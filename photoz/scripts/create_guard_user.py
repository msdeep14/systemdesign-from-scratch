#!/usr/bin/env python3
"""
Creates a single predictable test user for TrueCourse Guard scenarios.
Run this after docker-compose brings up the database.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bses.settings")
django.setup()

from django.contrib.auth.models import User  # noqa: E402

from users.models import UserProfile  # noqa: E402

USERNAME = "guardtest"
PASSWORD = "password123"

if not User.objects.filter(username=USERNAME).exists():
    user = User.objects.create_user(username=USERNAME, password=PASSWORD)
    UserProfile.objects.create(
        user=user,
        username_display=USERNAME,
        first_name="Guard",
        last_name="Test",
    )
    print(f"Created test user: {USERNAME}")
else:
    print(f"Test user already exists: {USERNAME}")
