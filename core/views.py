from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.models import Role, RoleAssignment, User
from accounts.permissions import can_manage, has_role, units_in_scope
from norms.models import Framework, Indicator
from org.models import OrgUnit
from portfolio.models import PortfolioEntry


@login_required
def home(request):
    u = request.user
    ctx = {
        "faculties": OrgUnit.objects.filter(kind=OrgUnit.Kind.FACULTY, is_active=True).count(),
        "departments": OrgUnit.objects.filter(kind=OrgUnit.Kind.DEPARTMENT, is_active=True).count(),
        "frameworks": Framework.objects.count(),
        "indicators": Indicator.objects.count(),
        "my_entries": u.portfolio.count(),
        "my_roles": u.roles.select_related("org_unit"),
    }
    if can_manage(u):
        ctx["pending_users"] = User.objects.filter(is_active=False, last_login__isnull=True).count()
    if has_role(u, Role.HEAD, Role.DEAN, Role.DIRECTOR, Role.ADMIN):
        if has_role(u, Role.ADMIN, Role.DIRECTOR):
            q = PortfolioEntry.objects.filter(status=PortfolioEntry.Status.SUBMITTED)
        else:
            teachers = RoleAssignment.objects.filter(
                role=Role.TEACHER, org_unit__in=units_in_scope(u, (Role.HEAD, Role.DEAN))).values("user_id")
            q = PortfolioEntry.objects.filter(status=PortfolioEntry.Status.SUBMITTED, owner_id__in=teachers)
        ctx["to_review"] = q.exclude(owner=u).count()
    from django.db.models import Q
    from django.utils import timezone

    from capa.access import visible_plans
    from capa.models import Action

    ctx["my_overdue"] = Action.objects.filter(
        Q(responsible=u) | Q(plan__owner=u), state=Action.State.PLANNED, due_date__lt=timezone.localdate(),
        plan__state="in_progress").select_related("plan")
    from management.models import Decision

    ctx["my_decisions"] = Decision.objects.filter(responsible=u, state=Decision.State.OPEN).select_related("review")
    plans = visible_plans(u)
    ctx["open_plans"] = plans.exclude(state__in=["closed", "cancelled"]).count()
    ctx["overdue_plans"] = sum(1 for p in plans if p.overdue)
    return render(request, "home.html", ctx)


@login_required
def journal(request):
    from django.core.exceptions import PermissionDenied

    from core.models import AuditLog

    if not can_manage(request.user):
        raise PermissionDenied
    return render(request, "journal.html", {"rows": AuditLog.objects.select_related("user")[:300]})


def csrf_failure(request, reason=""):
    """Вместо технической страницы Django — понятное объяснение: форма устарела после нового входа."""
    return render(request, "csrf_failure.html", status=403)


def health(request):
    """Для проверки сервера: отвечает «ok», если программа и база работают."""
    from django.db import connection
    from django.http import HttpResponse

    with connection.cursor() as c:
        c.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


def _settings_form(data=None):
    from django import forms

    from core import config

    current = config.get_many()
    fields = {}
    for s in config.SPECS:
        kw = {"label": s.label, "help_text": s.help, "min_value": s.min, "max_value": s.max, "initial": current[s.key]}
        fields[s.key] = forms.IntegerField(**kw) if s.kind is int else forms.DecimalField(decimal_places=2, **kw)
    return type("SettingsForm", (forms.Form,), fields)(data), current


@login_required
def settings_page(request):
    """Настройки Центра: пороги и правила, которые меняются без программиста. Каждое изменение — в журнал."""
    from django.contrib import messages
    from django.core.exceptions import PermissionDenied
    from django.shortcuts import redirect
    from django.utils.translation import gettext as _

    from core import config
    from core.models import Setting, log

    if not can_manage(request.user):
        raise PermissionDenied
    form, current = _settings_form(request.POST or None)
    if request.method == "POST" and form.is_valid():
        changed = 0
        for s in config.SPECS:
            new = form.cleaned_data[s.key]
            if new != current[s.key]:
                obj, _created = Setting.objects.update_or_create(key=s.key, defaults={"value": str(new)})
                log(request.user, "update", obj, f"Настройка «{s.label}»: было {current[s.key]}, стало {new}")
                changed += 1
        messages.success(request, _("Сохранено изменений: %(n)s.") % {"n": changed})
        return redirect("settings")
    groups = {}
    for s in config.SPECS:
        groups.setdefault(str(s.group), []).append(form[s.key])
    return render(request, "settings.html", {"form": form, "groups": groups.items()})
