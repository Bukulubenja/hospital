# services.py

from .models import ServiceGate, Visit


def is_gate_cleared(visit, service_type: str) -> bool:
    """Return True if the given visit has a cleared gate of this type."""
    return ServiceGate.objects.filter(
        visit=visit,
        service_type=service_type,
        is_cleared=True,
    ).exists()


def can_enter_doctor_gate(visit) -> bool:
    """A patient may enter the doctor's room once their consultation gate is cleared."""
    return is_gate_cleared(visit, ServiceGate.GateType.CONSULTATION)


def can_enter_lab_gate(visit) -> bool:
    """A patient may proceed to the lab once their lab gate is cleared."""
    return is_gate_cleared(visit, ServiceGate.GateType.LAB)


def can_enter_pharmacy_gate(visit) -> bool:
    """A patient may proceed to pharmacy once their pharmacy gate is cleared."""
    return is_gate_cleared(visit, ServiceGate.GateType.PHARMACY)


def visit_status_after_consultation(visit) -> str:
    """
    Route a visit onward once the doctor finishes with it: to the lab if
    tests were ordered, to pharmacy if drugs were prescribed, otherwise
    the visit is done.
    """
    if visit.lab_orders.exists():
        return Visit.Status.WAITING_LAB
    if visit.prescriptions.exists():
        return Visit.Status.WAITING_PHARMACY
    return Visit.Status.COMPLETED