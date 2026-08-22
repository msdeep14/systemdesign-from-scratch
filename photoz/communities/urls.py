from django.urls import path

from . import views

urlpatterns = [
    path("", views.list_communities, name="list_communities"),
    path("create/", views.create_community, name="create_community"),
    path("<int:id>/", views.community_detail, name="community_detail"),
    path("<int:id>/invite/", views.invite_member, name="invite_member"),
    path("respond/<int:id>/", views.respond_invitation, name="respond_invitation"),
]
