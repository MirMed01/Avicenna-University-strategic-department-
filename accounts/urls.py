from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

app_name = "accounts"
urlpatterns = [
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("password/", auth_views.PasswordChangeView.as_view(template_name="form.html",
         extra_context={"title": "Сменить пароль"}, success_url="/"), name="password"),
    path("users/", views.users, name="users"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/toggle/", views.toggle_user, name="toggle_user"),
    path("users/<int:pk>/roles/<int:role_pk>/remove/", views.role_remove, name="role_remove"),
]

login_view = auth_views.LoginView.as_view(template_name="accounts/login.html", authentication_form=LoginForm)
