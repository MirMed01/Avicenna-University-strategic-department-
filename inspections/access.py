"""Кто что может в проверках."""

from accounts.models import Role
from accounts.permissions import VIEW_ALL, can_manage, has_role, unit_in_scope, units_in_scope

from .models import Inspection


def visible_inspections(user):
    qs = Inspection.objects.select_related("org_unit", "lead_expert")
    if has_role(user, *VIEW_ALL):
        return qs
    units = units_in_scope(user, (Role.HEAD, Role.DEAN, Role.TEACHER))
    return qs.filter(org_unit__in=units)


def can_view(user, insp):
    return has_role(user, *VIEW_ALL) or unit_in_scope(user, insp.org_unit, (Role.HEAD, Role.DEAN, Role.TEACHER))


def can_lead(user, insp):
    """Ведёт проверку: менять статус, пересчитывать, писать заключение и выводы."""
    return can_manage(user) or (insp.lead_expert_id == user.pk)


def can_fill(user, task):
    """Заполнять: эксперты Центра — любой инструмент; кафедра — то, что адресовано ей."""
    insp = task.inspection
    if insp.state != Inspection.State.COLLECTING:
        return False
    if can_lead(user, insp) or has_role(user, Role.EXPERT):
        return True
    respondent = task.version.instrument.respondent
    if respondent in ("head",):
        return unit_in_scope(user, insp.org_unit, (Role.HEAD,))
    if respondent == "dean":
        return unit_in_scope(user, insp.org_unit, (Role.DEAN,))
    if respondent in ("teacher", "examiner"):
        return unit_in_scope(user, insp.org_unit, (Role.HEAD, Role.TEACHER))
    return False
