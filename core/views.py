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
