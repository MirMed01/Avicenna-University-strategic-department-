"""Готовность и ориентировочный прогноз решения по правилам IAAR для программной аккредитации.

Правила (руководство IAAR, 4-е изд., 2025, раздел «Принятие решений»):
  отказ   — хотя бы один «неудовлетворительно» или «предполагает улучшение» у 60 % и более критериев;
  7 лет   — «предполагает улучшение» не более 5 %, «сильных» не менее 15 %;
  5 лет   — не более 15 %, сильные есть;
  3 года  — не более 30 %, сильные есть;
  1 год   — остальное (менее 60 %).
Решение принимает Совет IAAR; программа показывает только ориентир.
"""

from decimal import Decimal

from django.utils.translation import gettext as _

from .models import Rating

WEAK = (Rating.IMPROVE, Rating.UNSATISFACTORY)


def counts(assessments):
    c = {r: 0 for r in Rating.values}
    c[""] = 0
    for a in assessments:
        c[a.rating] += 1
    return c


def years_label(years):
    if years == 0:
        return _("отказ в аккредитации")
    return {7: _("аккредитация на 7 лет"), 5: _("аккредитация на 5 лет"), 3: _("аккредитация на 3 года"),
            1: _("аккредитация на 1 год")}[years]


def forecast(assessments):
    c = counts(assessments)
    total = sum(c.values())
    rated = total - c[""]
    if not rated:
        return {"rated": 0, "total": total, "years": None, "counts": c}
    improve = Decimal(c[Rating.IMPROVE]) / rated * 100
    strong = Decimal(c[Rating.STRONG]) / rated * 100
    if c[Rating.UNSATISFACTORY] or improve >= 60:
        years = 0
    elif improve <= 5 and strong >= 15:
        years = 7
    elif improve <= 15 and c[Rating.STRONG]:
        years = 5
    elif improve <= 30 and c[Rating.STRONG]:
        years = 3
    else:
        years = 1
    return {"rated": rated, "total": total, "years": years, "label": years_label(years), "counts": c,
            "improve_pct": improve.quantize(Decimal("0.1")), "strong_pct": strong.quantize(Decimal("0.1")),
            "rated_pct": round(100 * rated / total) if total else 0}


def standard_of(a):
    node = a.criterion
    while node.parent_id:
        node = node.parent
    return node


def by_standard(assessments):
    """Итог по каждому стандарту — как в конце раздела самоотчёта."""
    groups = {}
    for a in assessments:
        groups.setdefault(standard_of(a), []).append(a)
    rows = []
    for std, items in groups.items():
        c = counts(items)
        rows.append({"std": std, "total": len(items), "counts": c, "rated": len(items) - c[""],
                     "missing_measures": sum(1 for a in items if a.rating in WEAK and not a.measures.strip()),
                     "no_evidence": sum(1 for a in items if a.rating and not a.evidence.strip() and not a.files.all())})
    rows.sort(key=lambda r: (r["std"].order, r["std"].code))
    return rows
