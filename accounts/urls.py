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

class ThrottledLoginView(auth_views.LoginView):
    """Вход с защитой от подбора пароля: после N неудач подряд вход по этому email закрыт на M минут (аудит 16.10.2026)."""

    template_name = "accounts/login.html"
    authentication_form = LoginForm

    def post(self, request, *args, **kwargs):
        from datetime import timedelta

        from django.utils import timezone
        from django.utils.translation import gettext as _

        from core import config

        from .models import LoginFailure

        username = request.POST.get("username", "").strip().lower()[:254]
        since = timezone.now() - timedelta(minutes=config.get("login_lock_minutes"))
        recent = LoginFailure.objects.filter(username=username, at__gte=since)
        if username and recent.count() >= config.get("login_max_failures"):
            form = self.get_form()
            form.errors.clear()
            form.add_error(None, _("Слишком много неудачных попыток входа. Подождите %(m)s минут и попробуйте снова.")
                           % {"m": config.get("login_lock_minutes")})
            return self.render_to_response(self.get_context_data(form=form))
        response = super().post(request, *args, **kwargs)
        if request.user.is_authenticated:
            LoginFailure.objects.filter(username=username).delete()
            from core.models import log

            log(request.user, "login", request.user, "Вход в систему")
        elif username:
            LoginFailure.objects.create(username=username)
            LoginFailure.objects.filter(at__lt=since).delete()  # старые записи не копятся
        return response


login_view = ThrottledLoginView.as_view()
