from .permissions import VIEW_ALL, VERIFIERS, can_manage, has_role
from .models import Role


def roles(request):
    u = request.user
    if not u.is_authenticated:
        return {}
    return {
        "can_manage": can_manage(u),
        "can_view_all": has_role(u, *VIEW_ALL),
        "is_verifier": has_role(u, *VERIFIERS),
        "is_teacher": has_role(u, Role.TEACHER),
    }
