from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import override

from accounts.decorators import manager_required
from accounts.permissions import VIEW_ALL, can_manage, has_role
from core.models import log

from .forms import DecisionForm, DecisionReportForm, ReviewForm
from .inputs import collect
from .models import Decision, Review


@login_required
def index(request):
    if not has_role(request.user, *VIEW_ALL):
        raise PermissionDenied
    open_decisions = Decision.objects.filter(state=Decision.State.OPEN).select_related("review", "responsible")
    return render(request, "management/index.html", {"reviews": Review.objects.all(), "open_decisions": open_decisions,
                                                     "manager": can_manage(request.user)})


@manager_required
def create(request):
    today = timezone.localdate()
    form = ReviewForm(request.POST or None, initial={
        "title": _("Анализ со стороны руководства за %(year)s год") % {"year": today.year}, "date": today,
        "period_from": today.replace(month=1, day=1), "period_to": today})
    if form.is_valid():
        r = form.save(commit=False)
        r.created_by = request.user
        r.save()
        r.inputs = collect(r.period_from, r.period_to, exclude_review=r)
        r.save(update_fields=["inputs"])
        log(request.user, "create", r, f"Анализ со стороны руководства «{r}»")
        return redirect("management:detail", r.pk)
    return render(request, "form.html", {"form": form, "title": _("Анализ со стороны руководства"),
                                         "hint": _("Программа сама соберёт сводку за период: проверки, несоответствия, планы исправления, опросы, Стратегию, процессы, риски, анализ тестов и выполнение прошлых решений.")})


def _get(request, pk):
    r = get_object_or_404(Review, pk=pk)
    if not (has_role(request.user, *VIEW_ALL) or r.decisions.filter(responsible=request.user).exists()):
        raise PermissionDenied
    return r


@login_required
def detail(request, pk):
    r = _get(request, pk)
    manager = can_manage(request.user)
    decisions = [(d, manager or d.responsible_id == request.user.pk) for d in r.decisions.select_related("responsible")]
    return render(request, "management/detail.html", {"r": r, "i": r.inputs, "manager": manager, "decisions": decisions,
                                                      "decision_form": DecisionForm(), "report_form": DecisionReportForm()})


@manager_required
def edit(request, pk):
    r = get_object_or_404(Review, pk=pk)
    form = ReviewForm(request.POST or None, instance=r)
    if form.is_valid():
        form.save()
        log(request.user, "update", r, f"«{r}»: изменены сведения заседания")
        return redirect("management:detail", pk)
    return render(request, "form.html", {"form": form, "title": str(r)})


@manager_required
def refresh(request, pk):
    r = get_object_or_404(Review, pk=pk)
    if request.method != "POST" or r.state != Review.State.DRAFT:
        raise PermissionDenied
    r.inputs = collect(r.period_from, r.period_to, exclude_review=r)
    r.save(update_fields=["inputs"])
    messages.success(request, _("Сводка обновлена."))
    return redirect("management:detail", pk)


@manager_required
def mark_held(request, pk):
    r = get_object_or_404(Review, pk=pk)
    if request.method != "POST" or r.state != Review.State.DRAFT:
        raise PermissionDenied
    r.state = Review.State.HELD
    r.save(update_fields=["state"])
    log(request.user, "update", r, f"«{r}»: заседание проведено, сводка зафиксирована")
    return redirect("management:detail", pk)


@manager_required
def decision_add(request, pk):
    r = get_object_or_404(Review, pk=pk)
    form = DecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.save(commit=False)
        d.review = r
        d.save()
        log(request.user, "create", r, f"«{r}»: решение «{d.text[:80]}», срок {d.due_date:%d.%m.%Y}")
    elif request.method == "POST":
        messages.error(request, _("Заполните решение и срок."))
    return redirect("management:detail", pk)


@login_required
def decision_report(request, pk):
    d = get_object_or_404(Decision.objects.select_related("review"), pk=pk)
    if not (can_manage(request.user) or d.responsible_id == request.user.pk) or request.method != "POST":
        raise PermissionDenied
    form = DecisionReportForm(request.POST, instance=d)
    if form.is_valid():
        d = form.save(commit=False)
        d.done_at = timezone.localdate() if d.state == Decision.State.DONE else None
        d.save()
        with override("ru"):  # журнал ведётся по-русски
            log(request.user, "update", d.review, f"«{d.review}»: решение «{d.text[:60]}» — {d.get_state_display().lower()}")
    return redirect("management:detail", d.review_id)
