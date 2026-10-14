from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from accounts.models import Role, RoleAssignment, User
from accounts.permissions import can_verify_portfolio, can_view_portfolio, has_role, units_in_scope

from .forms import PortfolioEntryForm, ReviewForm
from .models import EntryKind, PortfolioEntry

S = PortfolioEntry.Status


def _summary(entries):
    """Короткая сводка по подтверждённым записям — на ней потом считаются показатели Стратегии."""
    verified = [e for e in entries if e.status == S.VERIFIED]
    return {
        "total": len(entries),
        "verified": len(verified),
        "scopus_wos": sum(1 for e in verified if e.kind == EntryKind.PUBLICATION and e.indexing in ("scopus", "wos", "scopus_wos")),
        "certification": sum(1 for e in verified if e.kind == EntryKind.CERTIFICATION),
        "mobility": sum(1 for e in verified if e.kind == EntryKind.MOBILITY),
    }


def _grouped(entries):
    groups = {}
    for e in entries:
        groups.setdefault(e.get_kind_display(), []).append(e)
    return groups.items()


@login_required
def my(request):
    return show(request, request.user.pk)


@login_required
def show(request, user_pk):
    owner = get_object_or_404(User, pk=user_pk)
    if not can_view_portfolio(request.user, owner):
        raise PermissionDenied
    entries = list(owner.portfolio.select_related("reviewed_by"))
    units = [a.org_unit for a in owner.roles.select_related("org_unit") if a.role == Role.TEACHER]
    return render(request, "portfolio/show.html", {
        "owner": owner, "is_owner": owner == request.user, "groups": _grouped(entries),
        "summary": _summary(entries), "units": units,
        "can_verify": can_verify_portfolio(request.user, owner),
    })


def _own_entry(request, pk):
    entry = get_object_or_404(PortfolioEntry, pk=pk)
    if entry.owner != request.user:
        raise PermissionDenied
    return entry


@login_required
def create(request):
    form = PortfolioEntryForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.owner = request.user
        entry.status = S.SUBMITTED if "submit" in request.POST else S.DRAFT
        entry.save()
        messages.success(request, _("Запись добавлена и отправлена на проверку.") if entry.status == S.SUBMITTED
                         else _("Запись добавлена."))
        return redirect("portfolio:my")
    return render(request, "portfolio/form.html", {"form": form, "title": _("Новая запись портфолио")})


@login_required
def edit(request, pk):
    entry = _own_entry(request, pk)
    form = PortfolioEntryForm(request.POST or None, request.FILES or None, instance=entry)
    if form.is_valid():
        entry = form.save(commit=False)
        if entry.status == S.VERIFIED:
            # Изменили подтверждённое — нужно подтвердить заново.
            messages.info(request, _("Запись изменена и снова отправлена на проверку."))
            entry.status = S.SUBMITTED
        elif "submit" in request.POST:
            entry.status = S.SUBMITTED
        entry.save()
        return redirect("portfolio:my")
    return render(request, "portfolio/form.html", {"form": form, "title": _("Изменить запись"), "entry": entry})


@login_required
def delete(request, pk):
    entry = _own_entry(request, pk)
    if request.method == "POST":
        if entry.file:
            entry.file.delete(save=False)
        entry.delete()
        messages.success(request, _("Запись удалена."))
        return redirect("portfolio:my")
    return render(request, "confirm.html", {"title": _("Удалить запись «%(title)s»?") % {"title": entry.title},
                                            "text": _("Отменить это нельзя."),
                                            "back": "/portfolio/"})


@login_required
def submit(request, pk):
    entry = _own_entry(request, pk)
    if request.method == "POST" and entry.status in (S.DRAFT, S.REJECTED):
        entry.status = S.SUBMITTED
        entry.save(update_fields=["status", "updated_at"])
        messages.success(request, _("Отправлено на проверку."))
    return redirect("portfolio:my")


@login_required
def review(request, pk):
    entry = get_object_or_404(PortfolioEntry, pk=pk)
    if not can_verify_portfolio(request.user, entry.owner):
        raise PermissionDenied
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and request.POST.get("decision") in ("verify", "reject"):
        if request.POST["decision"] == "reject" and not form.cleaned_data["comment"]:
            messages.error(request, _("Чтобы вернуть запись, напишите, что исправить."))
        else:
            entry.status = S.VERIFIED if request.POST["decision"] == "verify" else S.REJECTED
            entry.reviewed_by, entry.reviewed_at = request.user, timezone.now()
            entry.review_comment = form.cleaned_data["comment"]
            entry.save()
            messages.success(request, _("Подтверждено.") if entry.status == S.VERIFIED else _("Возвращено на исправление."))
    return redirect(request.POST.get("next") or "portfolio:queue")


@login_required
def queue(request):
    """Записи на проверке у преподавателей, которых пользователь вправе подтверждать."""
    if has_role(request.user, Role.ADMIN, Role.DIRECTOR):
        entries = PortfolioEntry.objects.filter(status=S.SUBMITTED)
    else:
        units = units_in_scope(request.user, (Role.HEAD, Role.DEAN))
        teacher_ids = RoleAssignment.objects.filter(role=Role.TEACHER, org_unit__in=units).values("user_id")
        entries = PortfolioEntry.objects.filter(status=S.SUBMITTED, owner_id__in=teacher_ids)
    entries = entries.exclude(owner=request.user).select_related("owner").order_by("updated_at")
    return render(request, "portfolio/queue.html", {"entries": entries, "form": ReviewForm()})


@login_required
def download(request, pk):
    entry = get_object_or_404(PortfolioEntry, pk=pk)
    if not entry.file or not can_view_portfolio(request.user, entry.owner):
        raise Http404
    return FileResponse(entry.file.open("rb"), as_attachment=False, filename=entry.file.name.rsplit("/", 1)[-1])
