from django.urls import path

from . import views

urlpatterns = [
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("<str:username>/", views.profile_view, name="profile"),
    path("<str:username>/edit/", views.edit_profile_view, name="edit_profile"),
    path("<str:username>/delete/", views.delete_account_view, name="delete_account"),
    path("<str:username>/follow/", views.toggle_follow_view, name="toggle_follow"),
]
