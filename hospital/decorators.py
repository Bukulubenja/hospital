from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def role_required(*allowed_roles):
    """
    Restrict a view to authenticated users whose `.role` is one of
    `allowed_roles`.

    Usage:
        @role_required("DOCTOR")
        def doctor_only_view(request):
            ...

        @role_required("DOCTOR", "NURSE")
        def clinical_staff_view(request):
            ...
    """

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.role not in allowed_roles:
                raise PermissionDenied("You do not have access to this page.")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator