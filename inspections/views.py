from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from accounts.decorators import manager_required
from core.models import log
from instruments.scoring import parse

from .access import can_fill, can_lead, can_view, visible_inspections
from .forms import AddTaskForm, FindingForm, InspectionForm
from .models import Answer, Finding, Inspection, Task, calculate
from .radar import radar

St = Inspection.State


@login_required
def index(request):
    return render(request, "inspections/index.html", {"rows": visible_inspections(request.user)})


@manager_required
def create(request):
    form = InspectionForm(request.POST or None, initial={"org_unit": request.GET.get("unit")})
    if form.is_valid():
        with transaction.atomic():
            insp = form.save(commit=False)
            insp.created_by = request.user
            insp.save()
            for v in form.cleaned_data["instruments"]:
                Task.objects.create(inspection=insp, version=v)
            log(request.user, "create", insp, f"Назначена проверка «{insp}»")
        return redirect("inspections:detail", insp.pk)
    return render(request, "form.html", {"form": form, "title": _("Назначить проверку")})


def _get(request, pk):
    insp = get_object_or_404(Inspection.objects.select_related("org_unit", "lead_expert"), pk=pk)
    if not can_view(request.user, insp):
        raise PermissionDenied
    return insp


@login_required
def detail(request, pk):
    insp = _get(request, pk)
    tasks = [(t, can_fill(request.user, t)) for t in insp.tasks.select_related("version__instrument", "filled_by")]
    results = list(insp.results.select_related("indicator"))
    lead = can_lead(request.user, insp)
    return render(request, "inspections/detail.html", {
        "insp": insp, "tasks": tasks, "results": results, "radar": radar(results),
        "findings": insp.findings.select_related("created_by", "plan"), "lead": lead,
        "finding_form": FindingForm(), "task_form": AddTaskForm(),
        "submitted": sum(1 for t, _ in tasks if t.status == Task.Status.SUBMITTED)})


TRANSITIONS = {
    # gettext_noop: в журнал текст идёт по-русски, а сообщение на экране переводится при показе.
    "start": (St.PLANNED, St.COLLECTING, gettext_noop("Начат сбор данных")),
    "review": (St.COLLECTING, St.REVIEW, gettext_noop("Сбор закрыт, показатели посчитаны")),
    "reopen": (St.REVIEW, St.COLLECTING, gettext_noop("Возвращено на сбор данных")),
    "close": (St.REVIEW, St.CLOSED, gettext_noop("Проверка закрыта")),
    "cancel": (None, St.CANCELLED, gettext_noop("Проверка отменена")),
}


@login_required
def transition(request, pk, action):
    insp = _get(request, pk)
    if not can_lead(request.user, insp) or request.method != "POST" or action not in TRANSITIONS:
        raise PermissionDenied
    src, dst, text = TRANSITIONS[action]
    if (src and insp.state != src) or insp.state in (St.CLOSED, St.CANCELLED):
        messages.error(request, _("Это действие сейчас недоступно."))
        return redirect("inspections:detail", pk)
    if action == "review" and not insp.tasks.filter(status=Task.Status.SUBMITTED).exists():
        messages.error(request, _("Ни одно заполнение не сдано — считать нечего."))
        return redirect("inspections:detail", pk)
    if action == "reopen" and not request.POST.get("comment", "").strip():
        messages.error(request, _("Напишите, что нужно дособрать."))
        return redirect("inspections:detail", pk)
    with transaction.atomic():
        if action == "review":
            calculate(insp)
        if action == "close":
            insp.conclusion = request.POST.get("conclusion", "").strip()
            insp.closed_at = timezone.now()
        insp.state = dst
        insp.save()
        comment = request.POST.get("comment", "").strip()
        log(request.user, action, insp, f"«{insp}»: {text}" + (f". {comment}" if comment else ""))
    messages.success(request, _(text) + ".")
    return redirect("inspections:detail", pk)


@login_required
def recalc(request, pk):
    insp = _get(request, pk)
    if not can_lead(request.user, insp) or request.method != "POST" or insp.state != St.REVIEW:
        raise PermissionDenied
    calculate(insp)
    messages.success(request, _("Пересчитано (например, после изменения порогов)."))
    return redirect("inspections:detail", pk)


@login_required
def add_task(request, pk):
    insp = _get(request, pk)
    if not can_lead(request.user, insp) or insp.state not in (St.PLANNED, St.COLLECTING):
        raise PermissionDenied
    form = AddTaskForm(request.POST or None)
    if form.is_valid():
        Task.objects.create(inspection=insp, version=form.cleaned_data["version"], label=form.cleaned_data["label"])
    return redirect("inspections:detail", pk)


@login_required
def fill(request, task_pk):
    task = get_object_or_404(Task.objects.select_related("inspection__org_unit", "version__instrument"), pk=task_pk)
    insp = task.inspection
    if not can_view(request.user, insp):
        raise PermissionDenied
    editable = can_fill(request.user, task)
    items = list(task.version.items())
    saved = {a.item_id: a for a in task.answers.all()}
    errors = {}
    if request.method == "POST":
        if not editable:
            raise PermissionDenied
        submit = "submit" in request.POST
        values = {}
        for it in items:
            try:
                values[it.pk] = parse(it, request.POST.get(f"i{it.pk}"))
            except ValueError as e:
                errors[it.pk] = str(e)
            else:
                if submit and it.required and values[it.pk] is None:
                    errors[it.pk] = _("Обязательный пункт")
                if it.type == it.Type.CHOICE and values[it.pk] is not None and values[it.pk] not in it.option_list():
                    errors[it.pk] = _("Выберите вариант из списка")
        if not errors or not submit:
            with transaction.atomic():
                for it in items:
                    if it.pk in errors:
                        continue
                    a = saved.get(it.pk) or Answer(task=task, item=it)
                    a.set_value(values[it.pk])
                    a.save()
                task.filled_by = request.user
                task.status = Task.Status.SUBMITTED if submit and not errors else Task.Status.DRAFT
                task.submitted_at = timezone.now() if task.status == Task.Status.SUBMITTED else None
                task.save()
            if task.status == Task.Status.SUBMITTED:
                log(request.user, "submit", insp, f"«{insp}»: сдано «{task}»")
                messages.success(request, _("Сдано. Спасибо!"))
                return redirect("inspections:detail", insp.pk)
            if errors:
                messages.error(request, _("Сохранено как черновик. Исправьте пункты, отмеченные красным."))
            else:
                messages.success(request, _("Черновик сохранён."))
            saved = {a.item_id: a for a in task.answers.all()}
        else:
            messages.error(request, _("Не сдано: исправьте пункты, отмеченные красным. Остальное можно сохранить черновиком."))
    raw = lambda it: request.POST.get(f"i{it.pk}", "") if request.method == "POST" else _raw(saved.get(it.pk))
    sections = []
    for s in task.version.sections.all():
        sections.append((s, [(it, raw(it), errors.get(it.pk), saved.get(it.pk)) for it in items if it.section_id == s.pk]))
    return render(request, "inspections/fill.html", {"task": task, "insp": insp, "sections": sections, "editable": editable})


def _raw(answer):
    if answer is None:
        return ""
    v = answer.value()
    if v is None:
        return ""
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return answer.display()


@login_required
def reopen_task(request, task_pk):
    task = get_object_or_404(Task, pk=task_pk)
    if not can_lead(request.user, task.inspection) or request.method != "POST" or task.inspection.state != St.COLLECTING:
        raise PermissionDenied
    task.status = Task.Status.DRAFT
    task.save(update_fields=["status"])
    log(request.user, "reopen", task.inspection, f"«{task.inspection}»: заполнение «{task}» возвращено на доработку")
    return redirect("inspections:detail", task.inspection_id)


@login_required
def add_finding(request, pk):
    insp = _get(request, pk)
    if not can_lead(request.user, insp) or insp.state != St.REVIEW:
        raise PermissionDenied
    form = FindingForm(request.POST or None)
    if form.is_valid():
        f = form.save(commit=False)
        f.inspection, f.created_by = insp, request.user
        f.save()
        log(request.user, "create", insp, f"«{insp}»: находка эксперта — {f.text[:80]}")
    return redirect("inspections:detail", pk)


@login_required
def delete_finding(request, pk):
    f = get_object_or_404(Finding, pk=pk, auto=False)
    if not can_lead(request.user, f.inspection) or f.inspection.state != St.REVIEW or request.method != "POST":
        raise PermissionDenied
    if hasattr(f, "plan"):
        messages.error(request, _("По находке уже есть план исправления — её нельзя удалить."))
        return redirect("inspections:detail", f.inspection_id)
    log(request.user, "delete", f.inspection, f"«{f.inspection}»: удалена находка — {f.text[:80]}")
    f.delete()
    return redirect("inspections:detail", f.inspection_id)
