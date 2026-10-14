from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.decorators import manager_required
from accounts.models import Role
from accounts.permissions import VIEW_ALL, can_manage, has_role, unit_in_scope
from core.models import log

from .forms import AssessmentForm, AssignForm, CycleForm, EvidenceFileForm
from .models import Assessment, Cycle, EvidenceFile, Rating
from .readiness import WEAK, by_standard, forecast, standard_of


def can_view(user, cycle):
    if has_role(user, *VIEW_ALL) or cycle.lead_id == user.pk or cycle.assessments.filter(responsible=user).exists():
        return True
    return bool(cycle.org_unit and unit_in_scope(user, cycle.org_unit, (Role.DEAN,)))


def can_lead(user, cycle):
    return can_manage(user) or cycle.lead_id == user.pk


def can_edit(user, a):
    return can_lead(user, a.cycle) or a.responsible_id == user.pk


def _assessments(cycle):
    return list(cycle.assessments.select_related("criterion__parent__parent", "responsible").prefetch_related("files"))


@login_required
def index(request):
    cycles = [c for c in Cycle.objects.select_related("version__framework", "org_unit") if can_view(request.user, c)]
    rows = [(c, forecast(_assessments(c))) for c in cycles]
    return render(request, "accreditation/index.html", {"rows": rows})


@manager_required
def create(request):
    form = CycleForm(request.POST or None)
    if form.is_valid():
        with transaction.atomic():
            c = form.save()
            c.ensure_assessments()
            log(request.user, "create", c, f"Подготовка к аккредитации «{c}»: {c.assessments.count()} критериев")
        return redirect("accreditation:detail", c.pk)
    return render(request, "form.html", {"form": form, "title": _("Новая подготовка к аккредитации")})


@manager_required
def edit(request, pk):
    c = get_object_or_404(Cycle, pk=pk)
    form = CycleForm(request.POST or None, instance=c)
    if form.is_valid():
        form.save()
        log(request.user, "update", c, f"Подготовка к аккредитации «{c}» изменена (срок {c.deadline:%d.%m.%Y})")
        return redirect("accreditation:detail", pk)
    return render(request, "form.html", {"form": form, "title": c.title})


@login_required
def detail(request, pk):
    c = get_object_or_404(Cycle.objects.select_related("version__framework", "org_unit", "lead"), pk=pk)
    if not can_view(request.user, c):
        raise PermissionDenied
    items = _assessments(c)
    f = request.GET.get("f", "")
    shown = items
    if f == "unrated":
        shown = [a for a in items if not a.rating]
    elif f == "weak":
        shown = [a for a in items if a.rating in WEAK]
    elif f == "mine":
        shown = [a for a in items if a.responsible_id == request.user.pk]
    groups = []
    for a in shown:
        std = standard_of(a)
        if not groups or groups[-1][0] != std:
            groups.append((std, []))
        groups[-1][1].append(a)
    return render(request, "accreditation/detail.html", {
        "c": c, "fc": forecast(items), "standards": by_standard(items), "groups": groups, "f": f,
        "lead": can_lead(request.user, c), "assign_form": AssignForm(), "today": timezone.localdate()})


@login_required
def assign(request, pk):
    c = get_object_or_404(Cycle, pk=pk)
    if not can_lead(request.user, c) or request.method != "POST":
        raise PermissionDenied
    form = AssignForm(request.POST)
    if form.is_valid():
        std_code = form.cleaned_data["standard"]
        ids = [a.pk for a in _assessments(c) if standard_of(a).code == std_code]
        Assessment.objects.filter(pk__in=ids).update(responsible=form.cleaned_data["responsible"])
        log(request.user, "update", c, f"«{c}»: стандарт {std_code} поручен {form.cleaned_data['responsible']}")
        messages.success(request, _("Назначено."))
    return redirect("accreditation:detail", pk)


@login_required
def assessment(request, pk):
    a = get_object_or_404(Assessment.objects.select_related("cycle", "criterion__parent__parent", "responsible"), pk=pk)
    if not can_view(request.user, a.cycle):
        raise PermissionDenied
    editable = can_edit(request.user, a)
    form = AssessmentForm(request.POST or None, instance=a, can_assign=can_lead(request.user, a.cycle))
    if request.method == "POST":
        if not editable:
            raise PermissionDenied
        if form.is_valid():
            a = form.save(commit=False)
            a.updated_by, a.updated_at = request.user, timezone.now()
            a.save()
            log(request.user, "update", a.cycle, f"«{a.cycle}»: критерий {a.criterion.code} — {a.get_rating_display() or 'без оценки'}")
            messages.success(request, _("Сохранено."))
            nxt = a.cycle.assessments.filter(criterion__order__gt=a.criterion.order, rating="").order_by("criterion__order").first()
            if "next" in request.POST and nxt:
                return redirect("accreditation:assessment", nxt.pk)
            return redirect(f"/accreditation/{a.cycle_id}/#c{a.pk}")
    return render(request, "accreditation/assessment.html", {
        "a": a, "form": form, "editable": editable, "file_form": EvidenceFileForm(), "std": standard_of(a)})


@login_required
def upload(request, pk):
    a = get_object_or_404(Assessment, pk=pk)
    if not can_edit(request.user, a) or request.method != "POST":
        raise PermissionDenied
    form = EvidenceFileForm(request.POST, request.FILES)
    if form.is_valid():
        ef = form.save(commit=False)
        ef.assessment, ef.uploaded_by = a, request.user
        ef.save()
        log(request.user, "create", a.cycle, f"«{a.cycle}»: к критерию {a.criterion.code} добавлен документ «{ef.title}»")
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("accreditation:assessment", pk)


@login_required
def download(request, pk):
    ef = get_object_or_404(EvidenceFile.objects.select_related("assessment__cycle"), pk=pk)
    if not can_view(request.user, ef.assessment.cycle):
        raise Http404
    return FileResponse(ef.file.open("rb"), filename=ef.file.name.rsplit("/", 1)[-1])


@login_required
def export_docx(request, pk):
    c = get_object_or_404(Cycle.objects.select_related("version__framework"), pk=pk)
    if not can_view(request.user, c):
        raise PermissionDenied
    from .report import self_assessment_docx

    resp = HttpResponse(self_assessment_docx(c, _assessments(c)),
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    resp["Content-Disposition"] = f'attachment; filename="samootchet-{c.pk}.docx"'
    return resp
