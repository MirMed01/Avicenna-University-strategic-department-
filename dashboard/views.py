from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.decorators import manager_required
from accounts.models import Role
from accounts.permissions import VIEW_ALL, has_role, units_in_scope
from core.models import log
from norms.models import Indicator
from org.models import OrgUnit

from . import data, reports
from .models import IndicatorValue


def _scope(user):
    if has_role(user, *VIEW_ALL):
        return OrgUnit.objects.all(), _("весь университет")
    units = units_in_scope(user, (Role.DEAN, Role.HEAD))
    if not units.exists():
        raise PermissionDenied
    top = min(units, key=lambda u: u.depth)
    return units, top.name


def _year(request):
    try:
        return int(request.GET.get("year") or timezone.localdate().year)
    except ValueError:
        return timezone.localdate().year


@login_required
def index(request):
    units, scope_name = _scope(request.user)
    year = _year(request)
    ctx = data.collect(units, year)
    ctx.update(scope_name=scope_name, strategy=data.strategy(year) if has_role(request.user, *VIEW_ALL) else None,
               can_export=has_role(request.user, *VIEW_ALL))
    return render(request, "dashboard/index.html", ctx)


@manager_required
def strategy_value(request, indicator_pk):
    ind = get_object_or_404(Indicator, pk=indicator_pk)
    year = _year(request)
    current = IndicatorValue.objects.filter(indicator=ind, year=year).first()
    if request.method == "POST":
        raw = request.POST.get("value", "").strip().replace(",", ".")
        if raw == "" and current:
            current.delete()
            log(request.user, "delete", ind, f"Стратегия: {ind.code} за {year} — значение удалено")
            return redirect(f"/dashboard/?year={year}#strategy")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            messages.error(request, _("Введите число."))
        else:
            IndicatorValue.objects.update_or_create(indicator=ind, year=year, defaults={
                "value": value, "note": request.POST.get("note", "").strip()[:255], "entered_by": request.user})
            log(request.user, "update", ind, f"Стратегия: {ind.code} за {year} = {value.normalize():f}")
            return redirect(f"/dashboard/?year={year}#strategy")
    return render(request, "dashboard/strategy_value.html", {"ind": ind, "year": year, "current": current})


def _export_allowed(user):
    if not has_role(user, *VIEW_ALL):
        raise PermissionDenied


@login_required
def export_xlsx(request):
    _export_allowed(request.user)
    year = _year(request)
    content = reports.xlsx(data.collect(OrgUnit.objects.all(), year), data.strategy(year))
    resp = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="kanon-{year}.xlsx"'
    return resp


@login_required
def export_docx(request):
    _export_allowed(request.user)
    year = _year(request)
    content = reports.docx(data.collect(OrgUnit.objects.all(), year), data.strategy(year))
    resp = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    resp["Content-Disposition"] = f'attachment; filename="kanon-otchet-{year}.docx"'
    return resp


@login_required
def unit_history_view(request, unit_pk):
    """История показателей кафедры или факультета по годам."""
    from accounts.permissions import unit_in_scope
    from core import config

    from .history import unit_history

    unit = get_object_or_404(OrgUnit, pk=unit_pk)
    if not (has_role(request.user, *VIEW_ALL) or unit_in_scope(request.user, unit, (Role.HEAD, Role.DEAN))):
        raise PermissionDenied
    trend = config.get("trend_years")
    return render(request, "dashboard/history.html", {"unit": unit, "h": unit_history(unit, trend), "trend": trend})
