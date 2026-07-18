from rest_framework.permissions import BasePermission

from ..models import User


class IsPatientRole(BasePermission):
    """DRF equivalent of hospital.decorators.role_required("PATIENT") — this
    API surface is patient-app-only."""

    message = "You do not have access to this endpoint."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.PATIENT
        )
