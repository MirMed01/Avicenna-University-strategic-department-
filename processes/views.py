from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.decorators import manager_required
from accounts.permissions import can_manage
from core import config
from core.models import log
from dashboard.models import IndicatorValue
from inspections.models import Result
from norms.models import Indicator

from .forms import ProcessForm, RiskForm
from .models import Process, Risk, strategy_shares


def _can_edit(user, process):
    """Паспорт и риски правит Центр и владелец процесса."""
    return can_manage(user) or (process is not None and process.owner_id == user.pk)


@login_required
def index(request):
    level = request.GET.get("level") if request.GET.get("level") in Process.Level.values else Process.Level.UNIVERSITY
    all_processes = list(Process.objects.prefetch_related("indicators", "risks", "instruments").select_related("owner"))
    processes = [p for p in all_processes if p.level == level]
    high, medium = config.get("risk_high"), config.get("risk_medium")

    def row(p, depth):
        open_risks = [r for r in p.risks.all() if not r.is_closed]
        return {"p": p, "depth": depth, "gaps": p.gaps() if depth == 0 else [], "risks": len(open_risks),
                "instruments": list(p.instruments.all()),
                "high": sum(1 for r in open_risks if r.level(high, medium) == "high")}

    groups = []
    for value, label in Process.Group.choices:
        rows = []
        for p in processes:
            if p.group == value and p.parent_id is None:
                rows.append(row(p, 0))
                rows += [row(c, 1) for c in processes if c.parent_id == p.pk]
        groups.append((label, rows))
    digital, full, n_key = strategy_shares(all_processes)
    counts = {v: sum(1 for p in all_processes if p.level == v) for v in Process.Level.values}
    return render(request, "processes/index.html", {
        "groups": groups, "digital": digital, "full": full, "n_key": n_key, "manager": can_manage(request.user),
        "level": level, "levels": [(v, l, counts[v]) for v, l in Process.Level.choices],
        "n_top": sum(1 for p in processes if p.parent_id is None), "n_sub": sum(1 for p in processes if p.parent_id),
        "uncovered": [p for p in processes if p.is_active and not p.instruments.all()]})


def _indicator_status(ind):
    """Последнее значение по университету (если вносилось) и сколько кафедр ниже нормы по последним проверкам."""
    yearly = ind.yearly_values.order_by("-year").first()
    latest = {}
    for r in Result.objects.filter(indicator=ind, inspection__state__in=["review", "closed"]).select_related(
            "inspection").order_by("inspection__created_at"):
        latest[r.inspection.org_unit_id] = r  # остаётся последняя проверка каждой кафедры
    below = sum(1 for r in latest.values() if r.status in ("mild", "severe"))
    return {"ind": ind, "yearly": yearly, "units": len(latest), "below": below}


@login_required
def detail(request, pk):
    p = get_object_or_404(Process.objects.select_related("owner"), pk=pk)
    high, medium = config.get("risk_high"), config.get("risk_medium")
    risks = [(r, r.level(high, medium)) for r in p.risks.all()]
    nodes = p.norm_nodes.select_related("version__framework").order_by("version__framework__title", "order", "code")
    return render(request, "processes/detail.html", {
        "p": p, "gaps": p.gaps(), "risks": risks, "nodes": nodes, "editable": _can_edit(request.user, p),
        "children": p.children.prefetch_related("instruments"), "instruments": p.instruments.all(),
        "indicators": [_indicator_status(i) for i in p.indicators.select_related("node__version__framework")]})


@login_required
def process_form(request, pk=None):
    p = get_object_or_404(Process, pk=pk) if pk else None
    if not (can_manage(request.user) if p is None else _can_edit(request.user, p)):
        raise PermissionDenied
    form = ProcessForm(request.POST or None, instance=p)
    if form.is_valid():
        obj = form.save()
        log(request.user, "update" if pk else "create", obj, f"Процесс СМК «{obj}»: паспорт {'изменён' if pk else 'создан'}")
        return redirect("processes:detail", obj.pk)
    return render(request, "form.html", {"form": form, "title": _("Паспорт процесса"),
                                         "hint": _("Показатели выбираются из справочника норм — пороги задаются там же.")})


@login_required
def risk_form(request, pk=None, risk_pk=None):
    risk = get_object_or_404(Risk, pk=risk_pk) if risk_pk else None
    process = risk.process if risk else get_object_or_404(Process, pk=pk)
    if not _can_edit(request.user, process):
        raise PermissionDenied
    form = RiskForm(request.POST or None, instance=risk)
    if form.is_valid():
        r = form.save(commit=False)
        r.process = process
        r.save()
        log(request.user, "update" if risk else "create", process,
            f"Процесс «{process}»: риск «{r.title}» ({r.likelihood}×{r.impact}){' — снят' if r.is_closed else ''}")
        return redirect("processes:detail", process.pk)
    return render(request, "form.html", {"form": form, "title": _("Риск процесса «%(p)s»") % {"p": process.title},
                                         "hint": _("Вероятность и последствия — от 1 (очень низкие) до 5 (очень высокие).")})


@login_required
def risk_map(request):
    """Карта рисков 5×5: сколько открытых рисков в каждой клетке «вероятность × последствия»."""
    high, medium = config.get("risk_high"), config.get("risk_medium")
    risks = list(Risk.objects.filter(is_closed=False, process__is_active=True).select_related("process"))
    grid = []
    for lk in range(5, 0, -1):
        grid.append((lk, [{"impact": im, "level": "high" if lk * im >= high else "medium" if lk * im >= medium else "low",
                           "risks": [r for r in risks if r.likelihood == lk and r.impact == im]} for im in range(1, 6)]))
    top = sorted(risks, key=lambda r: -r.score)[:15]
    return render(request, "processes/risks.html", {"grid": grid, "top": [(r, r.level(high, medium)) for r in top],
                                                    "total": len(risks)})


@manager_required
def save_strategy(request):
    """Записать посчитанные по реестру показатели Стратегии 4.2 и 4.3 за текущий год."""
    if request.method != "POST":
        raise PermissionDenied
    digital, full, n = strategy_shares()
    year = timezone.localdate().year
    saved = 0
    for code, value in (("4.2", digital), ("4.3", full)):
        ind = Indicator.objects.filter(node__version__framework__code="tsmu-strategy-2030", code=code).first()
        if ind is None or value is None:
            continue
        IndicatorValue.objects.update_or_create(indicator=ind, year=year, defaults={
            "value": Decimal(value), "note": f"по реестру процессов: ключевых процессов {n}", "entered_by": request.user})
        log(request.user, "update", ind, f"Стратегия: {ind.code} за {year} = {value} (по реестру процессов)")
        saved += 1
    if saved:
        messages.success(request, _("Значения записаны в мониторинг Стратегии за %(year)s год.") % {"year": year})
    else:
        messages.error(request, _("Нет ключевых процессов или показателей Стратегии 4.2/4.3 — записывать нечего."))
    return redirect("processes:index")
