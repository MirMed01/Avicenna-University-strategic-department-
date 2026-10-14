from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from core.models import log

from .decorators import manager_required
from .forms import ProfileForm, RegisterForm, RoleAssignmentForm
from .models import Role, RoleAssignment, User


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegisterForm(request.POST or None)
    if form.is_valid():
        user = form.save()
        log(None, "register", user, f"Заявка на регистрацию: {user.full_name}, {user.get_requested_role_display()} — {user.requested_unit}")
        return render(request, "accounts/registered.html", {"user_obj": user})
    return render(request, "accounts/register.html", {"form": form})


@manager_required
def users(request):
    q = request.GET.get("q", "").strip()
    qs = User.objects.prefetch_related("roles__org_unit")
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q))
    pending = User.objects.filter(is_active=False, last_login__isnull=True).select_related("requested_unit")
    return render(request, "accounts/users.html", {"users": qs.filter(is_active=True), "pending": pending, "q": q,
                                                   "inactive": qs.filter(is_active=False, last_login__isnull=False)})


@manager_required
def user_detail(request, pk):
    target = get_object_or_404(User, pk=pk)
    initial = {}
    if target.requested_role:
        initial = {"role": target.requested_role, "org_unit": target.requested_unit}
    form = RoleAssignmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        ra, created = RoleAssignment.objects.get_or_create(
            user=target, role=form.cleaned_data["role"], org_unit=form.cleaned_data["org_unit"]
        )
        if created:
            log(request.user, "role_add", target, f"{target}: роль «{ra.get_role_display()}» в «{ra.org_unit}»")
        if not target.is_active:
            target.is_active = True
            target.requested_role, target.requested_unit = "", None
            target.save()
            log(request.user, "activate", target, f"Открыт доступ: {target}")
            messages.success(request, f"Доступ открыт: {target}")
        else:
            messages.success(request, "Роль добавлена.")
        return redirect("accounts:user_detail", pk)
    return render(request, "accounts/user_detail.html", {"target": target, "form": form,
                                                         "roles": target.roles.select_related("org_unit")})


@manager_required
def role_remove(request, pk, role_pk):
    ra = get_object_or_404(RoleAssignment, pk=role_pk, user_id=pk)
    if request.method == "POST":
        log(request.user, "role_remove", ra.user, f"{ra.user}: снята роль «{ra.get_role_display()}» в «{ra.org_unit}»")
        ra.delete()
        messages.success(request, "Роль снята.")
    return redirect("accounts:user_detail", pk)


@manager_required
def toggle_user(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        if target == request.user:
            messages.error(request, "Нельзя закрыть доступ самому себе.")
        elif not target.is_active and target.last_login is None and not target.roles.exists():
            # Заявка без роли — отклонить (удалить), чтобы не копились.
            log(request.user, "reject", target, f"Заявка отклонена: {target.full_name}, {target.email}")
            target.delete()
            messages.success(request, "Заявка отклонена.")
            return redirect("accounts:users")
        else:
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            log(request.user, "activate" if target.is_active else "deactivate", target,
                f"{'Открыт' if target.is_active else 'Закрыт'} доступ: {target}")
            messages.success(request, "Доступ открыт." if target.is_active else "Доступ закрыт.")
    return redirect("accounts:user_detail", pk)


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "Сохранено.")
        return redirect("accounts:profile")
    return render(request, "form.html", {"form": form, "title": "Мои данные"})
