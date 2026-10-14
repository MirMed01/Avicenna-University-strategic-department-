from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .permissions import can_manage


def manager_required(view):
    """Только администратор системы и директор Центра."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not can_manage(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
