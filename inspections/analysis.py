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
