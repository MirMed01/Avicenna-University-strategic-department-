from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, override

from accounts.decorators import manager_required
from core.models import AuditLog, log
from inspections.access import can_lead
from inspections.models import Finding, Inspection, Task

from .access import can_edit_plan, can_lead_plan, can_report_action, can_view_plan, visible_plans
from .forms import ActionForm, PlanCreateForm, PlanEditForm, ProblemForm
from .models import Action, Plan, Problem

S = Plan.State


@login_required
def index(request):
    plans = visible_plans(request.user)
    show = request.GET.get("show", "open")
    if show == "open":
        plans = plans.exclude(state__in=[S.CLOSED, S.CANCELLED])
    elif show == "overdue":
        plans = [p for p in plans if p.overdue]
    return render(request, "capa/index.html", {"plans": plans, "show": show})


@login_required
def create(request, finding_pk):
    finding = get_object_or_404(Finding.objects.select_related("inspection__org_unit", "result__indicator"), pk=finding_pk)
    insp = finding.inspection
    if not can_lead(request.user, insp) or insp.state not in (Inspection.State.REVIEW, Inspection.State.CLOSED):
        raise PermissionDenied
    if hasattr(finding, "plan"):
        return redirect("capa:detail", finding.plan.pk)
    ind = finding.result.indicator if finding.result_id else None
    suggested = list(Problem.objects.filter(is_active=True, indicators=ind)) if ind else []
    initial = {"title": _("Исправление: %(text)s") % {"text": finding.text[:200]}, "problem": suggested[0].pk if len(suggested) == 1 else None}
    if finding.result_id and finding.result.expected_threshold is not None:
        initial["effectiveness_criterion"] = _(
            "На повторной проверке «%(title)s» достигает порога уровня кафедры (%(threshold)s).") % {
            "title": finding.result.title, "threshold": f"{finding.result.expected_threshold.normalize():f}"}
    form = PlanCreateForm(request.POST or None, initial=initial, suggested=suggested)
    if form.is_valid():
        with transaction.atomic():
            plan = form.save(commit=False)
            plan.finding, plan.created_by = finding, request.user
            plan.save()
            # Типовое лечение диагноза — стартовый набор мероприятий; их можно править и удалять.
            for title in plan.problem.action_list():
                Action.objects.create(plan=plan, title=title, responsible=plan.owner, due_date=plan.due_date)
            log(request.user, "create", plan, f"{plan.ref}: диагноз «{plan.problem}» — {plan.org_unit}")
        messages.success(request, _("План создан. В него добавлены типовые мероприятия — проверьте и уточните их."))
        return redirect("capa:detail", plan.pk)
    return render(request, "capa/create.html", {"form": form, "finding": finding, "suggested": suggested})


def _get(request, pk):
    plan = get_object_or_404(Plan.objects.select_related("finding__inspection__org_unit", "finding__result__indicator",
                                                         "problem", "owner", "followup"), pk=pk)
    if not can_view_plan(request.user, plan):
        raise PermissionDenied
    return plan


@login_required
def detail(request, pk):
    plan = _get(request, pk)
    actions = [(a, can_report_action(request.user, a)) for a in plan.actions.select_related("responsible")]
    return render(request, "capa/detail.html", {
        "plan": plan, "actions": actions, "lead": can_lead_plan(request.user, plan),
        "editable": can_edit_plan(request.user, plan), "is_owner": request.user == plan.owner,
        "followup_result": plan.followup_result(), "action_form": ActionForm(initial={"due_date": plan.due_date, "responsible": plan.owner}),
        "history": AuditLog.objects.filter(object_type="plan", object_id=str(plan.pk)).select_related("user")})


@login_required
def edit(request, pk):
    plan = _get(request, pk)
    if not can_edit_plan(request.user, plan):
        raise PermissionDenied
    form = PlanEditForm(request.POST or None, instance=plan)
    if form.is_valid():
        form.save()
        log(request.user, "update", plan, f"{plan.ref}: план изменён")
        return redirect("capa:detail", pk)
    return render(request, "form.html", {"form": form, "title": _("%(ref)s: план") % {"ref": plan.ref}})


@login_required
def action_add(request, pk):
    plan = _get(request, pk)
    allowed = can_edit_plan(request.user, plan) or (plan.state == S.IN_PROGRESS and can_lead_plan(request.user, plan))
    if not allowed or request.method != "POST":
        raise PermissionDenied
    form = ActionForm(request.POST)
    if form.is_valid():
        a = form.save(commit=False)
        a.plan = plan
        a.save()
        log(request.user, "create", plan, f"{plan.ref}: добавлено мероприятие «{a}»")
    else:
        messages.error(request, _("Мероприятие не добавлено: заполните название и срок."))
    return redirect("capa:detail", pk)


@login_required
def action_delete(request, action_pk):
    a = get_object_or_404(Action, pk=action_pk)
    if not can_edit_plan(request.user, a.plan) or request.method != "POST":
        raise PermissionDenied
    log(request.user, "delete", a.plan, f"{a.plan.ref}: удалено мероприятие «{a}»")
    a.delete()
    return redirect("capa:detail", a.plan_id)


@login_required
def action_report(request, action_pk):
    a = get_object_or_404(Action.objects.select_related("plan"), pk=action_pk)
    if not can_report_action(request.user, a) or request.method != "POST":
        raise PermissionDenied
    decision = request.POST.get("decision")
    note = request.POST.get("note", "").strip()
    if decision not in ("done", "cancelled") or not note:
        messages.error(request, _("Опишите, что сделано (или почему мероприятие отменено)."))
        return redirect("capa:detail", a.plan_id)
    a.state, a.result_note, a.done_at = decision, note, timezone.now()
    a.save()
    with override("ru"):  # журнал — по-русски, даже если интерфейс на таджикском
        log(request.user, "update", a.plan, f"{a.plan.ref}: «{a}» — {a.get_state_display().lower()}: {note}")
    return redirect("capa:detail", a.plan_id)


# Переходы: (откуда, куда, кто: owner/lead, текст)
TRANSITIONS = {
    "submit": ((S.DRAFT,), S.SUBMITTED, "owner", gettext_lazy("План подан на утверждение")),
    "approve": ((S.SUBMITTED,), S.IN_PROGRESS, "lead", gettext_lazy("План утверждён, выполняется")),
    "return": ((S.SUBMITTED,), S.DRAFT, "lead", gettext_lazy("План возвращён на доработку")),
    "verify": ((S.IN_PROGRESS,), S.VERIFICATION, "owner", gettext_lazy("Мероприятия выполнены, ждёт оценки результативности")),
    "effective": ((S.VERIFICATION,), S.CLOSED, "lead", gettext_lazy("Результативно — план закрыт")),
    "not_effective": ((S.VERIFICATION,), S.IN_PROGRESS, "lead", gettext_lazy("Не помогло — план снова выполняется")),
    "cancel": ((S.DRAFT, S.SUBMITTED, S.IN_PROGRESS, S.VERIFICATION), S.CANCELLED, "lead", gettext_lazy("План отменён")),
}
NEEDS_COMMENT = {"return", "effective", "not_effective", "cancel"}


@login_required
def transition(request, pk, action):
    plan = _get(request, pk)
    if request.method != "POST" or action not in TRANSITIONS:
        raise PermissionDenied
    src, dst, who, text = TRANSITIONS[action]
    lead = can_lead_plan(request.user, plan)
    if not (lead or (who == "owner" and request.user == plan.owner)):
        raise PermissionDenied
    comment = request.POST.get("comment", "").strip()
    problem = None
    if plan.state not in src:
        problem = _("Это действие сейчас недоступно.")
    elif action in NEEDS_COMMENT and not comment:
        problem = _("Напишите комментарий: почему принято это решение.")
    elif action == "submit" and (not plan.root_cause.strip() or not plan.actions.exists()):
        problem = _("Чтобы подать план, нужны анализ причины и хотя бы одно мероприятие.")
    elif action == "verify":
        acts = list(plan.actions.all())
        if any(a.state == Action.State.PLANNED for a in acts):
            problem = _("Ещё есть невыполненные мероприятия: отметьте каждое как выполненное или отменённое.")
        elif not any(a.state == Action.State.DONE for a in acts):
            problem = _("Ни одно мероприятие не выполнено.")
    if problem:
        messages.error(request, problem)
        return redirect("capa:detail", pk)
    with transaction.atomic():
        plan.state = dst
        if action == "effective":
            plan.effectiveness_comment, plan.closed_at = comment, timezone.now()
        if action == "not_effective":
            plan.effectiveness_comment = comment
        plan.save()
        with override("ru"):  # журнал — по-русски
            log(request.user, action, plan, f"{plan.ref}: {text}" + (f". {comment}" if comment else ""))
    messages.success(request, str(text) + ".")
    return redirect("capa:detail", pk)


@login_required
def schedule_followup(request, pk):
    """Повторная проверка тем же инструментом, которым нашли отклонение."""
    plan = _get(request, pk)
    if not can_lead_plan(request.user, plan) or request.method != "POST" or plan.state != S.VERIFICATION:
        raise PermissionDenied
    src = plan.inspection
    with transaction.atomic():
        insp = Inspection.objects.create(title=f"Повторная: {src.title}", org_unit=src.org_unit, lead_expert=src.lead_expert,
                                         parent=src, created_by=request.user, note=f"Проверка результативности плана {plan.ref}.")
        seen = set()
        for t in src.tasks.select_related("version__instrument"):
            current = t.version.instrument.current_version()
            if current and current.instrument_id not in seen:
                seen.add(current.instrument_id)
                Task.objects.create(inspection=insp, version=current)
        plan.followup = insp
        plan.save(update_fields=["followup"])
        log(request.user, "create", plan, f"{plan.ref}: назначена повторная проверка")
    messages.success(request, _("Повторная проверка назначена. Начните в ней сбор данных."))
    return redirect("inspections:detail", insp.pk)


@login_required
def problems(request):
    return render(request, "capa/problems.html", {"problems": Problem.objects.prefetch_related("indicators")})


@manager_required
def problem_form(request, pk=None):
    obj = get_object_or_404(Problem, pk=pk) if pk else None
    form = ProblemForm(request.POST or None, instance=obj)
    if form.is_valid():
        p = form.save()
        log(request.user, "update" if pk else "create", p, f"Справочник проблем: «{p}»")
        return redirect("capa:problems")
    return render(request, "form.html", {"form": form, "title": _("Проблема качества")})
