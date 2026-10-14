from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from accounts.decorators import manager_required
from core.models import AuditLog, log

from .forms import FrameworkForm, IndicatorForm, LevelAssignmentForm, NormNodeForm
from .models import Framework, FrameworkVersion, Indicator, LevelAssignment, NormNode

THRESHOLD_FIELDS = ("threshold_weak", "threshold_medium", "threshold_high")


@login_required
def index(request):
    frameworks = Framework.objects.prefetch_related("versions")
    rows = []
    for f in frameworks:
        v = f.active_version()
        n = Indicator.objects.filter(node__version=v).count() if v else 0
        rows.append((f, v, n))
    return render(request, "norms/index.html", {"rows": rows})


@login_required
def version_detail(request, pk):
    version = get_object_or_404(FrameworkVersion.objects.select_related("framework"), pk=pk)
    nodes = list(version.nodes.prefetch_related("indicators__instrument_derived__version__instrument"))
    by_parent = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)
    ordered = []

    def walk(pid, depth):
        for n in sorted(by_parent.get(pid, []), key=lambda n: (n.order, n.code)):
            ordered.append((n, depth))
            walk(n.id, depth + 1)

    walk(None, 0)
    levels = LevelAssignment.objects.filter(framework=version.framework).select_related("org_unit").order_by("org_unit__path")
    history = AuditLog.objects.filter(object_type="indicator", object_id__in=[
        str(i.pk) for n in nodes for i in n.indicators.all()])[:20]
    return render(request, "norms/version.html", {"version": version, "nodes": ordered, "levels": levels,
                                                  "history": history, "versions": version.framework.versions.all()})


@manager_required
def framework_create(request):
    form = FrameworkForm(request.POST or None)
    if form.is_valid():
        with transaction.atomic():
            f = form.save()
            v = FrameworkVersion.objects.create(
                framework=f, version=form.cleaned_data["version"],
                effective_from=form.cleaned_data["effective_from"], source_url=form.cleaned_data["source_url"])
            log(request.user, "create", f, f"Новый документ-источник: «{f.title}», ред. {v.version}")
        return redirect("norms:version", v.pk)
    return render(request, "form.html", {"form": form, "title": _("Новый документ-источник норм")})


@manager_required
def node_create(request, version_pk):
    version = get_object_or_404(FrameworkVersion, pk=version_pk)
    parent = NormNode.objects.filter(pk=request.GET.get("parent"), version=version).first()
    form = NormNodeForm(request.POST or None, initial={"kind": NormNode.Kind.STANDARD if parent else NormNode.Kind.AREA})
    if form.is_valid():
        node = form.save(commit=False)
        node.version, node.parent = version, parent
        node.save()
        log(request.user, "create", node, f"{version}: добавлен раздел {node}")
        return redirect("norms:version", version.pk)
    title = _("Новый раздел в «%(parent)s»") % {"parent": parent} if parent else _("Новая область: %(version)s") % {"version": version}
    return render(request, "form.html", {"form": form, "title": title})


@manager_required
def node_edit(request, pk):
    node = get_object_or_404(NormNode, pk=pk)
    form = NormNodeForm(request.POST or None, instance=node)
    if form.is_valid():
        form.save()
        log(request.user, "update", node, f"{node.version}: изменён раздел {node}")
        return redirect("norms:version", node.version_id)
    return render(request, "form.html", {"form": form, "title": _("Раздел %(code)s") % {"code": node.code}})


@manager_required
def node_delete(request, pk):
    node = get_object_or_404(NormNode, pk=pk)
    if request.method == "POST":
        vid = node.version_id
        log(request.user, "delete", node, f"{node.version}: удалён раздел {node} со всем содержимым")
        node.delete()
        messages.success(request, _("Раздел удалён."))
        return redirect("norms:version", vid)
    n_ind = Indicator.objects.filter(node__in=_subtree(node)).count()
    return render(request, "confirm.html", {
        "title": _("Удалить раздел «%(node)s»?") % {"node": node},
        "text": _("Вместе с ним удалятся вложенные разделы и показатели (%(n)s). Отменить это нельзя.") % {"n": n_ind},
        "back": f"/norms/{node.version_id}/"})


def _subtree(node):
    ids, frontier = [node.id], [node.id]
    while frontier:
        frontier = list(NormNode.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        ids += frontier
    return ids


@manager_required
def indicator_create(request, node_pk):
    node = get_object_or_404(NormNode, pk=node_pk)
    form = IndicatorForm(request.POST or None)
    if form.is_valid():
        ind = form.save(commit=False)
        ind.node = node
        ind.save()
        log(request.user, "create", ind, f"Добавлен показатель {ind}; пороги {ind.thresholds_text()}")
        return redirect("norms:version", node.version_id)
    return render(request, "form.html", {"form": form, "title": _("Новый показатель в «%(node)s»") % {"node": node}})


@manager_required
def indicator_edit(request, pk):
    ind = get_object_or_404(Indicator, pk=pk)
    before = ind.thresholds_text()
    form = IndicatorForm(request.POST or None, instance=ind)
    if form.is_valid():
        ind = form.save()
        after = ind.thresholds_text()
        change = f"пороги (слабый / средний / высокий): {before} → {after}" if before != after else "изменено описание"
        log(request.user, "update", ind, f"Показатель {ind.code}: {change}")
        messages.success(request, _("Сохранено."))
        return redirect("norms:version", ind.node.version_id)
    history = AuditLog.objects.filter(object_type="indicator", object_id=str(ind.pk))
    return render(request, "norms/indicator_form.html", {"form": form, "ind": ind, "history": history})


@manager_required
def indicator_delete(request, pk):
    ind = get_object_or_404(Indicator, pk=pk)
    if request.method == "POST":
        vid = ind.node.version_id
        log(request.user, "delete", ind, f"Удалён показатель {ind}")
        ind.delete()
        return redirect("norms:version", vid)
    return render(request, "confirm.html", {"title": _("Удалить показатель «%(ind)s»?") % {"ind": ind}, "text": _("Отменить это нельзя."),
                                            "back": f"/norms/{ind.node.version_id}/"})


@manager_required
def level_set(request, version_pk):
    version = get_object_or_404(FrameworkVersion, pk=version_pk)
    form = LevelAssignmentForm(request.POST or None)
    if form.is_valid():
        la, _created = LevelAssignment.objects.update_or_create(
            org_unit=form.cleaned_data["org_unit"], framework=version.framework,
            defaults={"level": form.cleaned_data["level"]})
        log(request.user, "update", la, f"{version.framework}: для «{la.org_unit}» уровень «{la.get_level_display()}»")
        return redirect("norms:version", version.pk)
    return render(request, "form.html", {"form": form, "title": _("Уровень строгости: %(framework)s") % {"framework": version.framework},
                                         "hint": _("Уровень действует на выбранное подразделение и всё, что в него входит. "
                                                   "Если нигде не задан — средний.")})


@manager_required
def level_remove(request, pk):
    la = get_object_or_404(LevelAssignment, pk=pk)
    if request.method == "POST":
        version = la.framework.active_version()
        log(request.user, "delete", la, f"{la.framework}: для «{la.org_unit}» снята своя настройка уровня")
        la.delete()
        if version:
            return redirect("norms:version", version.pk)
    return redirect("norms:index")
