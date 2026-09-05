from django.urls import path

from . import views

urlpatterns = [
    path("upload/", views.upload_story, name="upload_story"),
    path("<int:id>/", views.view_story, name="view_story"),
]
