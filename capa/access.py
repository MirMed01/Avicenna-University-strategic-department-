from accounts.permissions import has_role, VIEW_ALL
from inspections.access import can_lead, can_view, visible_inspections

from .models import Plan


def visible_plans(user):
    qs = Plan.objects.select_related("finding__inspection__org_unit", "problem", "owner")
    if has_role(user, *VIEW_ALL):
        return qs
    return qs.filter(finding__inspection__in=visible_inspections(user))


def can_view_plan(user, plan):
    return can_view(user, plan.inspection)


def can_lead_plan(user, plan):
    """Утверждать, оценивать результативность, отменять: директор, админ, ведущий эксперт проверки."""
    return can_lead(user, plan.inspection)


def can_edit_plan(user, plan):
    """Писать анализ и мероприятия: ответственный за план и ведущий."""
    return plan.state in (Plan.State.DRAFT,) and (user == plan.owner or can_lead_plan(user, plan))


def can_report_action(user, action):
    plan = action.plan
    return plan.state == Plan.State.IN_PROGRESS and (
        user in (action.responsible, plan.owner) or can_lead_plan(user, plan))
