"""Входные данные анализа со стороны руководства — собираются программой за период (ISO 9001, п. 9.3.2)."""

from decimal import Decimal

from django.utils import timezone


def collect(period_from, period_to, exclude_review=None):
    from capa.models import Plan
    from core import config
    from dashboard.models import IndicatorValue
    from exams.models import ExamAnalysis
    from feedback.models import Campaign, Change
    from inspections.models import Finding, Inspection
    from processes.models import Risk, strategy_shares

    from .models import Decision

    def in_period(qs, field):
        return qs.filter(**{f"{field}__date__gte": period_from, f"{field}__date__lte": period_to})

    today = timezone.localdate()
    prev = Decision.objects.exclude(review=exclude_review) if exclude_review else Decision.objects.all()
    insp = in_period(Inspection.objects.filter(state__in=["review", "closed"]), "created_at")
    findings = Finding.objects.filter(inspection__in=insp)
    by_sev = {k: findings.filter(severity=k).count() for k in ("severe", "mild", "note", "opportunity", "strength")}
    plans = Plan.objects.all()
    open_plans = list(plans.exclude(state__in=["closed", "cancelled"]).select_related("finding__inspection"))
    camps = Campaign.objects.filter(closes_on__gte=period_from, closes_on__lte=period_to)
    year = period_to.year
    values = IndicatorValue.objects.filter(indicator__node__version__framework__code="tsmu-strategy-2030", year=year).select_related("indicator")
    met = sum(1 for v in values if v.indicator.meets(v.value, "medium"))
    s = config.get_many()
    exams = ExamAnalysis.objects.filter(exam_date__gte=period_from, exam_date__lte=period_to)
    low_exams = sum(1 for a in exams if a.data.get("alpha") is not None and Decimal(str(a.data["alpha"])) < a.alpha_min(s))
    digital, full, n_key = strategy_shares()
    high_risks = sum(1 for r in Risk.objects.filter(is_closed=False, process__is_active=True)
                     if r.level(s["risk_high"], s["risk_medium"]) == "high")
    return {
        "collected": today.isoformat(),
        "prev_decisions": {"total": prev.count(), "done": prev.filter(state="done").count(),
                           "open": prev.filter(state="open").count(),
                           "overdue": prev.filter(state="open", due_date__lt=today).count()},
        "inspections": {"count": insp.count(), "units": insp.values("org_unit").distinct().count(), **by_sev},
        "plans": {"opened": in_period(plans, "created_at").count(),
                  "closed_effective": in_period(plans.filter(state="closed"), "closed_at").count(),
                  "open": len(open_plans), "overdue": sum(1 for p in open_plans if p.overdue)},
        "feedback": {"campaigns": camps.count(), "responses": sum(c.response_count for c in camps),
                     "changes": Change.objects.filter(campaign__in=camps).count()},
        "strategy": {"year": year, "entered": values.count(), "met_medium": met},
        "processes": {"key": n_key, "full": full, "digital": digital, "high_risks": high_risks},
        "exams": {"count": exams.count(), "low_reliability": low_exams},
    }
