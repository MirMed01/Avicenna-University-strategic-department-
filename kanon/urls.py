from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts.urls import login_view
from core import views as core_views

admin.site.site_header = "Канон — администрирование"

urlpatterns = [
    path("", core_views.home, name="home"),
    path("journal/", core_views.journal, name="journal"),
    path("login/", login_view, name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/", include("accounts.urls")),
    path("structure/", include("org.urls")),
    path("norms/", include("norms.urls")),
    path("portfolio/", include("portfolio.urls")),
    path("admin/", admin.site.urls),
]
