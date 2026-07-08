from .models import User, Visit

# Visit states in which a doctor should be able to open a visit at all.
DOCTOR_ACCESSIBLE_STATUSES = {
    Visit.Status.WAITING_DOCTOR,
    Visit.Status.IN_CONSULTATION,
}


def can_doctor_access(user, visit: Visit) -> bool:
    """True if this user is the doctor assigned to the visit and it's at a stage they can act on."""
    return (
        user.role == User.Role.DOCTOR
        and visit.doctor_id == user.id
        and visit.status in DOCTOR_ACCESSIBLE_STATUSES
    )


def can_nurse_access(user, visit: Visit) -> bool:
    """
    True if this user is a nurse and the visit is still waiting on a doctor.

    Unlike doctors, nurses aren't individually assigned to a visit — any
    nurse can triage any patient waiting to be seen, same shared-pool model
    used for lab and pharmacy queues.
    """
    return user.role == User.Role.NURSE and visit.status == Visit.Status.WAITING_DOCTOR