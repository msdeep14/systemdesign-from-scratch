from django.urls import path

from . import views

urlpatterns = [
    path("upload/", views.upload_photo, name="upload_photo"),
    path("search/", views.search_view, name="search"),
    path("<int:id>/", views.photo_detail, name="photo_detail"),
    path("<int:id>/delete/", views.delete_photo, name="delete_photo"),
    path("<int:id>/like/", views.toggle_like, name="toggle_like"),
    path("<int:id>/comment/", views.add_comment, name="add_comment"),
]
