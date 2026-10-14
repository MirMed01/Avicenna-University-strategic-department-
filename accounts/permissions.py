"""Права доступа. Одно место, чтобы правила было легко прочитать и проверить тестами."""

from org.models import OrgUnit

from .models import Role

# Кто управляет справочниками (структура, нормы) и пользователями.
MANAGERS = (Role.ADMIN, Role.DIRECTOR)
# Кто видит весь университет (только чтение для ректора и экспертов).
VIEW_ALL = (Role.ADMIN, Role.DIRECTOR, Role.RECTOR, Role.EXPERT)
# Кто проверяет портфолио преподавателей своего подразделения.
VERIFIERS = (Role.HEAD, Role.DEAN, Role.DIRECTOR, Role.ADMIN)


def _assignments(user):
    if not user.is_authenticated:
        return []
    if not hasattr(user, "_role_cache"):
        user._role_cache = list(user.roles.select_related("org_unit"))
    return user._role_cache


def has_role(user, *roles):
    if user.is_authenticated and user.is_superuser:
        return True
    return any(a.role in roles for a in _assignments(user))


def can_manage(user):
    return has_role(user, *MANAGERS)


def units_in_scope(user, roles):
    """Подразделения, на которые у пользователя есть одна из ролей (вместе с вложенными)."""
    if user.is_authenticated and user.is_superuser:
        return OrgUnit.objects.all()
    paths = [a.org_unit.path for a in _assignments(user) if a.role in roles]
    if not paths:
        return OrgUnit.objects.none()
    from django.db.models import Q

    q = Q()
    for p in paths:
        q |= Q(path__startswith=p)
    return OrgUnit.objects.filter(q)


def unit_in_scope(user, unit, roles):
    if user.is_authenticated and user.is_superuser:
        return True
    return any(a.role in roles and unit.path.startswith(a.org_unit.path) for a in _assignments(user))


def can_view_portfolio(viewer, owner):
    if viewer == owner or has_role(viewer, *VIEW_ALL):
        return True
    owner_units = [a.org_unit for a in owner.roles.select_related("org_unit") if a.role == Role.TEACHER]
    return any(unit_in_scope(viewer, u, (Role.HEAD, Role.DEAN)) for u in owner_units)


def can_verify_portfolio(viewer, owner):
    if viewer == owner:
        return False  # своё не подтверждают
    if has_role(viewer, Role.ADMIN, Role.DIRECTOR):
        return True
    owner_units = [a.org_unit for a in owner.roles.select_related("org_unit") if a.role == Role.TEACHER]
    return any(unit_in_scope(viewer, u, (Role.HEAD, Role.DEAN)) for u in owner_units)
