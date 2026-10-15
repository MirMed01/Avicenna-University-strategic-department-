"""История показателей подразделения по годам: «было — стало» и предупреждение, если показатель ухудшается."""

from django.utils import timezone

from feedback.voting import summary
from inspections.models import Inspection
from norms.models import Indicator, effective_level

from .data import status


def _worse(prev, cur, direction):
    if prev is None or cur is None:
        return False
    return cur > prev if direction == Indicator.Direction.LOWER else cur < prev


def unit_history(unit, trend_years):
    """{"years": [...], "rows": [{code, title, cells, first, last, worsening}]}. Год проверки — по дате её создания,
    год опроса — по дате окончания приёма ответов. Если за год несколько значений — берётся последнее."""
    series = {}

    def put(code, title, ind, year, value, st):
        s = series.setdefault(code, {"code": code, "title": title, "ind": ind, "years": {}})
        s["years"][year] = {"value": value, "status": st}

    for insp in unit.inspections.filter(state__in=[Inspection.State.REVIEW, Inspection.State.CLOSED]).order_by("created_at"):
        year = timezone.localtime(insp.created_at).year
        for r in insp.results.select_related("indicator"):
            code = r.indicator.code if r.indicator else r.title.split(" ", 1)[0]
            put(code, r.title, r.indicator, year, r.value, r.status)
    for camp in unit.campaigns.order_by("closes_on", "created_at"):
        if not camp.results_visible:
            continue
        for d in summary(camp)[1]:
            ind = d["d"].indicator
            if not ind or d["value"] is None:
                continue
            lvl = ind.achieved_level(d["value"])
            put(ind.code, f"{ind.code} {ind.title}", ind, camp.closes_on.year, d["value"],
                status(lvl, effective_level(unit, ind.node.version.framework)))
    years = sorted({y for s in series.values() for y in s["years"]})
    rows = []
    for code in sorted(series):
        s = series[code]
        values = [(y, s["years"][y]["value"]) for y in sorted(s["years"]) if s["years"][y]["value"] is not None]
        direction = s["ind"].direction if s["ind"] else Indicator.Direction.HIGHER
        streak = 0
        for (_, a), (_, b) in zip(values, values[1:]):
            streak = streak + 1 if _worse(a, b, direction) else 0
        s["cells"] = [s["years"].get(y) for y in years]
        s["first"] = values[0] if values else None
        s["last"] = values[-1] if len(values) > 1 else None
        s["streak"] = streak
        s["worsening"] = streak >= trend_years
        rows.append(s)
    return {"years": years, "rows": rows}
