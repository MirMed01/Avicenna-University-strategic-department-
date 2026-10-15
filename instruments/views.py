from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from accounts.decorators import manager_required
from core.models import log

from .forms import DerivedForm, InstrumentForm, ItemForm, SectionForm
from .models import Derived, Instrument, InstrumentVersion, Item, Section
from .scoring import compute, parse


@login_required
def index(request):
    rows = [(i, i.latest_version(), i.current_version()) for i in Instrument.objects.prefetch_related("processes")]
    return render(request, "instruments/index.html", {"rows": rows})


@login_required
def version(request, pk):
    v = get_object_or_404(InstrumentVersion.objects.select_related("instrument"), pk=pk)
    sections = v.sections.prefetch_related("items__indicator__node__version__framework")
    derived = v.derived.select_related("numerator", "denominator", "section", "indicator__node__version__framework")
    return render(request, "instruments/version.html", {
        "v": v, "inst": v.instrument, "sections": sections, "derived": derived,
        "versions": v.instrument.versions.all()})


@manager_required
def create(request):
    form = InstrumentForm(request.POST or None)
    if form.is_valid():
        inst = form.save()
        v = InstrumentVersion.objects.create(instrument=inst, number=1)
        log(request.user, "create", inst, f"Новый инструмент «{inst}»")
        return redirect("instruments:version", v.pk)
    return render(request, "form.html", {"form": form, "title": _("Новый инструмент")})


@manager_required
def edit(request, pk):
    inst = get_object_or_404(Instrument, pk=pk)
    form = InstrumentForm(request.POST or None, instance=inst)
    if form.is_valid():
        form.save()
        log(request.user, "update", inst, f"Изменено описание инструмента «{inst}»")
        return redirect("instruments:version", inst.latest_version().pk)
    return render(request, "form.html", {"form": form, "title": _("Инструмент: %(inst)s") % {"inst": inst}})


def _draft_or_redirect(request, v):
    if not v.editable:
        messages.error(request, _("Опубликованную версию менять нельзя. Создайте новую версию."))
        return redirect("instruments:version", v.pk)
    return None


@manager_required
def publish(request, pk):
    v = get_object_or_404(InstrumentVersion, pk=pk)
    if request.method == "POST":
        try:
            v.publish()
            log(request.user, "publish", v.instrument, f"Опубликована {v}")
            messages.success(request, _("Версия опубликована. Теперь её можно использовать в проверках."))
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
    return redirect("instruments:version", pk)


@manager_required
def new_version(request, pk):
    v = get_object_or_404(InstrumentVersion, pk=pk)
    if request.method == "POST":
        try:
            draft = v.new_draft(note=request.POST.get("note", ""))
            log(request.user, "create", v.instrument, f"Создан черновик {draft}")
            return redirect("instruments:version", draft.pk)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
    return redirect("instruments:version", pk)


@manager_required
def section_form(request, version_pk, pk=None):
    v = get_object_or_404(InstrumentVersion, pk=version_pk)
    if r := _draft_or_redirect(request, v):
        return r
    section = get_object_or_404(Section, pk=pk, version=v) if pk else Section(version=v, order=v.sections.count())
    form = SectionForm(request.POST or None, instance=section)
    if form.is_valid():
        form.save()
        log(request.user, "update" if pk else "create", v.instrument, f"{v}: раздел «{section}»")
        return redirect("instruments:version", v.pk)
    return render(request, "form.html", {"form": form, "title": _("Раздел инструмента")})


@manager_required
def item_form(request, section_pk, pk=None):
    section = get_object_or_404(Section.objects.select_related("version"), pk=section_pk)
    if r := _draft_or_redirect(request, section.version):
        return r
    item = get_object_or_404(Item, pk=pk, section=section) if pk else None
    initial = {} if item else {"order": section.items.count(), "code": f"{section.order + 1}.{section.items.count() + 1}"}
    form = ItemForm(request.POST or None, instance=item, section=section, initial=initial)
    if form.is_valid():
        saved = form.save()
        log(request.user, "update" if pk else "create", section.version.instrument, f"{section.version}: пункт {saved}")
        return redirect("instruments:version", section.version_id)
    return render(request, "form.html", {"form": form, "title": _("Пункт в разделе «%(section)s»") % {"section": section}})


@manager_required
def derived_form(request, version_pk, pk=None):
    v = get_object_or_404(InstrumentVersion, pk=version_pk)
    if r := _draft_or_redirect(request, v):
        return r
    d = get_object_or_404(Derived, pk=pk, version=v) if pk else None
    form = DerivedForm(request.POST or None, instance=d, version=v)
    if form.is_valid():
        saved = form.save()
        log(request.user, "update" if pk else "create", v.instrument, f"{v}: расчёт {saved}")
        return redirect("instruments:version", v.pk)
    return render(request, "form.html", {"form": form, "title": _("Расчётный показатель"),
                                         "hint": _("Расчёт превращает ответы в число, которое программа сравнит с порогами нормы.")})


@manager_required
def delete_part(request, kind, pk):
    model = {"section": Section, "item": Item, "derived": Derived}[kind]
    obj = get_object_or_404(model, pk=pk)
    v = obj.version if kind != "item" else obj.section.version
    if r := _draft_or_redirect(request, v):
        return r
    if request.method == "POST":
        log(request.user, "delete", v.instrument, f"{v}: удалено «{obj}»")
        obj.delete()
        return redirect("instruments:version", v.pk)
    return render(request, "confirm.html", {"title": _("Удалить «%(obj)s»?") % {"obj": obj}, "text": _("Удаляется только из черновика."),
                                            "back": f"/instruments/{v.pk}/"})


@login_required
def try_fill(request, pk):
    """Пробное заполнение: показывает, как посчитаются показатели. Ничего не сохраняет."""
    v = get_object_or_404(InstrumentVersion.objects.select_related("instrument"), pk=pk)
    items = list(v.items())
    answers, errors, results = {}, {}, None
    if request.method == "POST":
        for it in items:
            try:
                answers[it.pk] = parse(it, request.POST.get(f"i{it.pk}"))
            except ValueError as e:
                errors[it.pk] = str(e)
        results = []
        for d in v.derived.select_related("indicator"):
            value, note = compute(d, items, answers)
            level = d.indicator.achieved_level(value) if (d.indicator and value is not None) else None
            results.append({"d": d, "value": value, "note": note, "level": level})
    sections = []
    for s in v.sections.all():
        sections.append((s, [(it, request.POST.get(f"i{it.pk}", ""), errors.get(it.pk)) for it in items if it.section_id == s.pk]))
    return render(request, "instruments/try.html", {"v": v, "sections": sections, "results": results})
