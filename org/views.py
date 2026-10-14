from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import manager_required
from accounts.models import Role
from core.models import log

from .forms import OrgUnitForm
from .models import OrgUnit


@login_required
def tree(request):
    show_closed = request.GET.get("closed") == "1"
    units = OrgUnit.objects.order_by("path") if show_closed else OrgUnit.objects.filter(is_active=True).order_by("path")
    units = list(units)
    # Сортировка дерева: родитель, затем его дети по порядку и названию.
    by_parent = {}
    for u in units:
        by_parent.setdefault(u.parent_id, []).append(u)
    for lst in by_parent.values():
        lst.sort(key=lambda u: (u.order, u.name))
    ids = {u.id for u in units}
    ordered = []

    def walk(pid):
        for u in by_parent.get(pid, []):
            ordered.append(u)
            walk(u.id)

    for root in [u for u in units if u.parent_id is None or u.parent_id not in ids]:
        ordered.append(root)
        walk(root.id)
    counts = {k: sum(1 for u in units if u.kind == k and u.is_active) for k in OrgUnit.Kind.values}
    return render(request, "org/tree.html", {"units": ordered, "show_closed": show_closed, "counts": counts})


@login_required
def detail(request, pk):
    unit = get_object_or_404(OrgUnit, pk=pk)
    staff = unit.role_assignments.select_related("user").order_by("role", "user__full_name")
    teachers = [a.user for a in staff if a.role == Role.TEACHER]
    return render(
        request,
        "org/detail.html",
        {"unit": unit, "staff": staff, "teachers": teachers, "children": unit.children.order_by("order", "name"),
         "blockers": unit.delete_blockers(),
         "inspections": unit.inspections.order_by("-created_at")[:10]},
    )


@manager_required
def create(request):
    initial = {}
    parent = OrgUnit.objects.filter(pk=request.GET.get("parent")).first()
    if parent:
        initial["parent"] = parent
        initial["kind"] = OrgUnit.Kind.DEPARTMENT if parent.kind == OrgUnit.Kind.FACULTY else OrgUnit.Kind.FACULTY
    form = OrgUnitForm(request.POST or None, initial=initial)
    if form.is_valid():
        unit = form.save()
        log(request.user, "create", unit, f"Добавлено: {unit.get_kind_display()} «{unit.name}» в «{unit.parent}»")
        messages.success(request, f"Добавлено: {unit.name}")
        return redirect("org:detail", unit.pk)
    return render(request, "form.html", {"form": form, "title": "Новое подразделение", "back": request.META.get("HTTP_REFERER")})


@manager_required
def edit(request, pk):
    unit = get_object_or_404(OrgUnit, pk=pk)
    before = f"«{unit.name}» в «{unit.parent}»"
    form = OrgUnitForm(request.POST or None, instance=unit)
    if form.is_valid():
        unit = form.save()
        log(request.user, "update", unit, f"Изменено: было {before}, стало «{unit.name}» в «{unit.parent}»")
        messages.success(request, "Сохранено.")
        return redirect("org:detail", unit.pk)
    return render(request, "form.html", {"form": form, "title": f"Изменить: {unit.name}"})


@manager_required
def delete(request, pk):
    unit = get_object_or_404(OrgUnit, pk=pk)
    blockers = unit.delete_blockers()
    if request.method == "POST" and not blockers:
        parent = unit.parent
        with transaction.atomic():
            log(request.user, "delete", unit, f"Удалено: {unit.get_kind_display()} «{unit.name}» из «{parent}»")
            unit.delete()
        messages.success(request, f"Удалено: {unit.name}")
        return redirect("org:detail", parent.pk) if parent else redirect("org:tree")
    return render(request, "org/delete.html", {"unit": unit, "blockers": blockers})


@manager_required
def toggle_active(request, pk):
    unit = get_object_or_404(OrgUnit, pk=pk)
    if request.method == "POST":
        units = unit.descendants()
        new = not unit.is_active
        if new and unit.parent and not unit.parent.is_active:
            messages.error(request, "Сначала восстановите вышестоящее подразделение.")
            return redirect("org:detail", pk)
        # Закрытие закрывает и вложенные; восстановление — только само подразделение.
        (units if not new else OrgUnit.objects.filter(pk=pk)).update(is_active=new)
        log(request.user, "archive" if not new else "restore", unit,
            f"{'Закрыто' if not new else 'Восстановлено'}: «{unit.name}»")
        messages.success(request, ("Восстановлено: " if new else "Закрыто: ") + unit.name)
    return redirect("org:detail", pk)
