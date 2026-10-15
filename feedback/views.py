import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from accounts.decorators import manager_required
from accounts.models import Role
from accounts.permissions import VIEW_ALL, can_manage, has_role, unit_in_scope, units_in_scope
from core.models import log
from norms.models import LEVEL_ORDER, effective_level

from .forms import CampaignForm, ChangeForm
from .models import Campaign, Change, TextAnswer
from .voting import VoteError, find_campaign, submit, summary, validate


def _status(level, expected):
    if not level:
        return "unknown"
    if level == "below":
        return "severe"
    return "ok" if LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(expected) else "mild"


def _can_view(user, c):
    return has_role(user, *VIEW_ALL) or unit_in_scope(user, c.org_unit, (Role.HEAD, Role.DEAN))


def _can_act(user, c):
    """Записать «вы сказали — мы сделали» может Центр, заведующий кафедрой и декан."""
    return can_manage(user) or unit_in_scope(user, c.org_unit, (Role.HEAD, Role.DEAN))


@login_required
def index(request):
    qs = Campaign.objects.select_related("org_unit", "version__instrument")
    if not has_role(request.user, *VIEW_ALL):
        qs = qs.filter(org_unit__in=units_in_scope(request.user, (Role.HEAD, Role.DEAN)))
    return render(request, "feedback/index.html", {"campaigns": qs})


@manager_required
def create(request):
    form = CampaignForm(request.POST or None)
    if form.is_valid():
        with transaction.atomic():
            c = form.save(commit=False)
            c.created_by = request.user
            c.save()
            c.add_codes(form.cleaned_data["code_count"])
            log(request.user, "create", c, f"Опрос студентов «{c}»: {form.cleaned_data['code_count']} кодов")
        return redirect("feedback:detail", c.pk)
    if not form.fields["version"].queryset.exists():
        messages.error(request, _("Нет опубликованной анкеты для студентов. Создайте её в разделе «Инструменты» (кто заполняет — студент)."))
    return render(request, "form.html", {"form": form, "title": _("Новый опрос студентов")})


@login_required
def detail(request, pk):
    c = get_object_or_404(Campaign.objects.select_related("org_unit", "version__instrument"), pk=pk)
    if not _can_view(request.user, c):
        raise PermissionDenied
    manager = can_manage(request.user)
    ctx = {"c": c, "manager": manager, "used": c.codes.filter(used=True).count(), "total": c.codes.count()}
    from core import config

    ctx["min_rate"] = config.get("feedback_min_rate")
    ctx["rate"] = round(100 * c.response_count / ctx["total"]) if ctx["total"] else None
    ctx["low_rate"] = ctx["rate"] is not None and not c.accepting and ctx["rate"] < ctx["min_rate"]
    ctx["can_change"] = _can_act(request.user, c)
    ctx["changes"] = c.changes.all()
    ctx["change_form"] = ChangeForm()
    if c.results_visible:
        rows, derived = summary(c)
        for d in derived:
            ind = d["d"].indicator
            d["expected"] = effective_level(c.org_unit, ind.node.version.framework) if ind else None
            d["level"] = ind.achieved_level(d["value"]) if (ind and d["value"] is not None) else None
            d["status"] = _status(d["level"], d["expected"])
        if not manager:  # кафедра видит только одобренные Центром комментарии
            for r in rows:
                if "texts" in r:
                    r["texts"] = [t for t in r["texts"] if t.decision == TextAnswer.Decision.PUBLIC]
        ctx.update(rows=rows, derived=derived)
    return render(request, "feedback/detail.html", ctx)


@manager_required
def codes(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    base = getattr(settings, "KANON_PUBLIC_URL", "") or request.build_absolute_uri("/")[:-1]
    slips = []
    for ac in c.codes.filter(used=False).order_by("id"):
        url = f"{base}/s/{ac.code}/"
        slips.append({"code": ac.code, "url": url, "qr": mark_safe(segno.make(url, error="m").svg_inline(scale=3, dark="#000"))})
    return render(request, "feedback/codes.html", {"c": c, "slips": slips, "entry": f"{base}/s/"})


@manager_required
def add_codes(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    if request.method == "POST":
        n = max(1, min(100, int(request.POST.get("n") or 10)))
        c.add_codes(n)
        log(request.user, "update", c, f"«{c}»: добавлено кодов: {n}")
    return redirect("feedback:detail", pk)


@manager_required
def toggle(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    if request.method == "POST":
        c.is_open = not c.is_open
        c.save(update_fields=["is_open"])
        log(request.user, "update", c, f"«{c}»: приём ответов {'открыт' if c.is_open else 'закрыт'}")
    return redirect("feedback:detail", pk)


@manager_required
def moderate(request, pk):
    t = get_object_or_404(TextAnswer, pk=pk)
    if request.method == "POST" and request.POST.get("decision") in TextAnswer.Decision.values:
        t.decision = request.POST["decision"]
        t.save(update_fields=["decision"])
    return redirect("feedback:detail", t.campaign_id)


@login_required
def change_add(request, pk):
    c = get_object_or_404(Campaign, pk=pk)
    if not _can_act(request.user, c) or request.method != "POST":
        raise PermissionDenied
    form = ChangeForm(request.POST)
    if form.is_valid():
        ch = form.save(commit=False)
        ch.campaign, ch.created_by = c, request.user
        ch.save()
        log(request.user, "create", c, f"«{c}»: вы сказали — мы сделали: {ch.done[:80]}")
        messages.success(request, _("Записано. Студенты увидят это на странице опросов."))
    else:
        messages.error(request, _("Заполните оба поля."))
    return redirect("feedback:detail", pk)


@login_required
def change_delete(request, pk):
    ch = get_object_or_404(Change, pk=pk)
    if not _can_act(request.user, ch.campaign) or request.method != "POST":
        raise PermissionDenied
    log(request.user, "delete", ch.campaign, f"«{ch.campaign}»: удалено «мы сделали»: {ch.done[:80]}")
    ch.delete()
    return redirect("feedback:detail", ch.campaign_id)


def public_changes(org_unit=None, limit=10):
    qs = Change.objects.filter(is_public=True).select_related("campaign__org_unit")
    if org_unit is not None:
        qs = qs.filter(campaign__org_unit=org_unit)
    return qs[:limit]


# ---------- Страницы для студента: без входа в систему ----------

def entry(request):
    code = request.GET.get("code", "").strip()
    if code:
        return redirect("student:vote", code=code.upper())
    return render(request, "feedback/public_entry.html", {"changes": public_changes()})


def vote(request, code):
    try:
        c = find_campaign(code)
    except VoteError as e:
        return render(request, "feedback/public_message.html", {"title": _("Не получилось"), "text": str(e)})
    errors, posted = {}, {}
    if request.method == "POST":
        answers, errors = validate(c, request.POST)
        if not errors:
            try:
                submit(code, answers)
            except VoteError as e:
                return render(request, "feedback/public_message.html", {"title": _("Не получилось"), "text": str(e)})
            return render(request, "feedback/public_message.html", {
                "title": _("Спасибо!"), "text": _("Ответ записан анонимно. Код больше не действует.")})
        posted = request.POST
    sections = []
    for s in c.version.sections.all():
        items = [(it, posted.get(f"i{it.pk}", ""), errors.get(it.pk)) for it in s.items.all()]
        sections.append((s, items))
    return render(request, "feedback/public_vote.html", {"c": c, "sections": sections, "code": code, "has_errors": bool(errors),
                                                         "changes": public_changes(c.org_unit, 5)})
