from django.urls import path

from . import views

urlpatterns = [
    path("", views.newsfeed, name="newsfeed"),
]
