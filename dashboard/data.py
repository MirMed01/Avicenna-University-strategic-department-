"""Сбор данных для панели и отчётов. Одна функция — и для страницы, и для Excel/Word."""

from decimal import Decimal

from django.utils import timezone

from accounts.models import Role, RoleAssignment
from capa.models import Plan
from feedback.models import Campaign
from feedback.voting import summary
from inspections.models import Inspection
from norms.models import LEVEL_ORDER, Framework, Indicator
from org.models import OrgUnit
from portfolio.models import EntryKind, Indexing, PortfolioEntry

from .models import IndicatorValue

STRATEGY = "tsmu-strategy-2030"


def status(level, expected):
    if not level:
        return "unknown"
    if level == "below":
        return "severe"
    return "ok" if LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(expected) else "mild"


def heatmap(units):
    """Строки — кафедры с последней посчитанной проверкой; столбцы — показатели."""
    rows, columns, unchecked = [], {}, []
    for dep in units.filter(kind=OrgUnit.Kind.DEPARTMENT, is_active=True).order_by("name"):
        insp = dep.inspections.filter(state__in=[Inspection.State.REVIEW, Inspection.State.CLOSED]).order_by("-created_at").first()
        cells = {}
        if insp:
            for r in insp.results.select_related("indicator"):
                code = r.indicator.code if r.indicator else r.title.split(" ", 1)[0]
                columns.setdefault(code, r.title)
                cells[code] = {"value": r.value, "status": r.status}
        camp = next((c for c in dep.campaigns.order_by("-created_at") if c.results_visible), None)
        if camp:
            from norms.models import effective_level

            for d in summary(camp)[1]:
                ind = d["d"].indicator
                if not ind or d["value"] is None:
                    continue
                columns.setdefault(ind.code, f"{ind.code} {ind.title}")
                lvl = ind.achieved_level(d["value"])
                cells[ind.code] = {"value": d["value"], "status": status(lvl, effective_level(dep, ind.node.version.framework))}
        if cells:
            bad = sum(1 for c in cells.values() if c["status"] in ("mild", "severe"))
            rows.append({"unit": dep, "inspection": insp, "cells": cells, "bad": bad})
        else:
            unchecked.append(dep)
    codes = sorted(columns)
    for row in rows:
        row["line"] = [row["cells"].get(c) for c in codes]
    rows.sort(key=lambda r: -r["bad"])
    return {"codes": codes, "titles": [columns[c] for c in codes], "rows": rows, "unchecked": unchecked}


def teachers():
    return RoleAssignment.objects.filter(role=Role.TEACHER, user__is_active=True).values("user_id").distinct()


def auto_values(year):
    """Показатели Стратегии, которые считаются по подтверждённым портфолио. Только по тем, кто есть в системе."""
    ids = {r["user_id"] for r in teachers()}
    n = len(ids)
    verified = PortfolioEntry.objects.filter(status=PortfolioEntry.Status.VERIFIED, owner_id__in=ids)

    def share(kind):
        if not n:
            return None
        k = verified.filter(kind=kind).values("owner_id").distinct().count()
        return (Decimal(k) / n * 100).quantize(Decimal("0.1"))

    pubs = PortfolioEntry.objects.filter(
        status=PortfolioEntry.Status.VERIFIED, kind=EntryKind.PUBLICATION, date_start__year=year,
        indexing__in=[Indexing.SCOPUS, Indexing.WOS, Indexing.SCOPUS_WOS]).count()
    note = f"по подтверждённым портфолио; преподавателей в системе: {n}"
    return {
        "2.2": (share(EntryKind.CERTIFICATION), note),
        "2.3": (share(EntryKind.MOBILITY), note),
        "3.1": (Decimal(pubs), f"подтверждённые статьи {year} г. в портфолио"),
    }


def strategy(year):
    fw = Framework.objects.filter(code=STRATEGY).first()
    if not fw or not fw.active_version():
        return []
    auto = auto_values(year)
    manual = {v.indicator_id: v for v in IndicatorValue.objects.filter(year=year, indicator__node__version=fw.active_version())}
    rows = []
    for ind in Indicator.objects.filter(node__version=fw.active_version()).order_by("node__order", "order"):
        if ind.pk in manual:
            value, source, auto_flag = manual[ind.pk].value, manual[ind.pk].note or "внесено Центром", False
        elif ind.code in auto and auto[ind.code][0] is not None:
            value, source, auto_flag = auto[ind.code][0], auto[ind.code][1], True
        else:
            value, source, auto_flag = None, "", False
        level = ind.achieved_level(value) if value is not None else None
        rows.append({"ind": ind, "value": value, "source": source, "auto": auto_flag,
                     "status": status(level, "medium") if value is not None else "nodata"})
    return rows


def plans_summary(plans):
    open_ = [p for p in plans if p.is_open]
    return {"open": len(open_), "overdue": [p for p in open_ if p.overdue],
            "closed": sum(1 for p in plans if p.state == Plan.State.CLOSED), "total": len(plans)}


def collect(user_units, year):
    from capa.models import Plan as P

    insp = Inspection.objects.filter(org_unit__in=user_units)
    plans = list(P.objects.filter(finding__inspection__org_unit__in=user_units).select_related("finding__inspection__org_unit", "owner", "problem"))
    camps = Campaign.objects.filter(org_unit__in=user_units).select_related("org_unit")
    return {
        "year": year,
        "departments": user_units.filter(kind=OrgUnit.Kind.DEPARTMENT, is_active=True).count(),
        "inspections_year": insp.filter(created_at__year=year).count(),
        "inspections_closed": insp.filter(created_at__year=year, state=Inspection.State.CLOSED).count(),
        "heat": heatmap(user_units),
        "plans": plans_summary(plans),
        "plan_list": plans,
        "campaigns": camps,
        "responses": sum(c.response_count for c in camps),
        "problems": _problem_stats(plans),
        "today": timezone.localdate(),
    }


def _problem_stats(plans):
    stats = {}
    for p in plans:
        stats.setdefault(str(p.problem), 0)
        stats[str(p.problem)] += 1
    return sorted(stats.items(), key=lambda kv: -kv[1])
