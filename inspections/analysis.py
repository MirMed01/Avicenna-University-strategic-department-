"""Подсказки эксперту по выводам проверки. Только предупреждения — решение остаётся за экспертом."""

from collections import Counter
from datetime import timedelta

from .models import Finding, Inspection

BELOW = (Finding.Severity.MILD, Finding.Severity.SEVERE)


def minor_clusters(inspection, n):
    """Разделы норм, где незначительных несоответствий не меньше n: по ISO 17021 это повод рассмотреть значительное."""
    counts, nodes = Counter(), {}
    for f in inspection.findings.filter(severity=Finding.Severity.MILD, result__indicator__isnull=False).select_related(
            "result__indicator__node"):
        node = f.result.indicator.node
        counts[node.pk] += 1
        nodes[node.pk] = node
    return [(nodes[k], v) for k, v in counts.items() if v >= n]


def repeated_findings(inspection, years):
    """Id выводов, у которых тот же показатель был ниже нормы на прошлых проверках этой кафедры за последние years лет."""
    since = inspection.created_at - timedelta(days=365 * years)
    earlier = Finding.objects.filter(
        inspection__org_unit=inspection.org_unit, inspection__created_at__lt=inspection.created_at,
        inspection__created_at__gte=since, severity__in=BELOW, result__indicator__isnull=False,
    ).exclude(inspection__state=Inspection.State.CANCELLED).values_list("result__indicator_id", flat=True)
    return set(inspection.findings.filter(severity__in=BELOW, result__indicator_id__in=set(earlier)).values_list("pk", flat=True))


def risk_ranking(units, s):
    """Кого проверять первым: баллы риска по последней проверке, опросу, повторам, просрочкам и давности. Веса — s (настройки)."""
    from django.utils import timezone

    from capa.models import Plan
    from dashboard.data import status
    from feedback.voting import summary
    from norms.models import effective_level
    from org.models import OrgUnit

    today = timezone.localdate()
    open_plans = list(Plan.objects.exclude(state__in=[Plan.State.CLOSED, Plan.State.CANCELLED]).select_related(
        "finding__inspection"))
    rows = []
    for dep in units.filter(kind=OrgUnit.Kind.DEPARTMENT, is_active=True).order_by("name"):
        last = dep.inspections.filter(state__in=[Inspection.State.REVIEW, Inspection.State.CLOSED]).order_by("-created_at").first()
        statuses, repeat, years = [], 0, None
        if last:
            statuses = [r.status for r in last.results.all()]
            repeat = len(repeated_findings(last, s["repeat_years"]))
            years = (today - timezone.localtime(last.created_at).date()).days // 365
        camp = next((c for c in dep.campaigns.order_by("-created_at") if c.results_visible), None)
        if camp:
            for d in summary(camp)[1]:
                ind = d["d"].indicator
                if ind and d["value"] is not None:
                    statuses.append(status(ind.achieved_level(d["value"]), effective_level(dep, ind.node.version.framework)))
        severe, mild = statuses.count("severe"), statuses.count("mild")
        overdue = sum(1 for p in open_plans if p.finding.inspection.org_unit_id == dep.pk and p.overdue)
        age = s["plan_w_never"] if last is None else s["plan_w_year"] * years
        score = (s["plan_w_severe"] * severe + s["plan_w_mild"] * mild + s["plan_w_repeat"] * repeat
                 + s["plan_w_overdue"] * overdue + age)
        planned = dep.inspections.filter(state__in=[Inspection.State.PLANNED, Inspection.State.COLLECTING]).first()
        rows.append({"unit": dep, "last": last, "years": years, "severe": severe, "mild": mild, "repeat": repeat,
                     "overdue": overdue, "score": score, "planned": planned})
    rows.sort(key=lambda r: (-r["score"], r["unit"].name))
    return rows
