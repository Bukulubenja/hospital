# services.py

import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    LabResult,
    Notification,
    Prescription,
    PrescriptionItem,
    QueueTicket,
    ServiceGate,
    Stock,
    StockTransaction,
    Visit,
    VisitInvoice,
)

_DURATION_RE = re.compile(r"(\d+)\s*(day|week|month)", re.IGNORECASE)
_DURATION_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}

# Rough per-patient consultation time used only to give the patient a
# ballpark wait estimate — there's no real scheduling/timing model to
# derive this from more precisely.
AVERAGE_CONSULTATION_MINUTES = 15


def patient_for_user(user):
    """Return the Patient record linked to this login, or None if unlinked."""
    return getattr(user, "patient_profile", None)


def create_notification(user, title, description=""):
    """Create a Notification for `user`, or no-op if `user` is None (e.g. a
    Patient not linked to a login account yet)."""
    if user is None:
        return None
    return Notification.objects.create(user=user, title=title, description=description)


def queue_snapshot_for_patient(patient):
    """
    Real (not fabricated) queue position for a patient's active, unserved
    ticket today: their queue number, how many unserved tickets are ahead
    of (and including) theirs, and a rough wait estimate from that count.
    Returns None if the patient has no active ticket today.
    """
    today = timezone.localdate()
    ticket = (
        QueueTicket.objects.filter(visit__patient=patient, created_at__date=today, served=False)
        .order_by("-created_at")
        .first()
    )
    if ticket is None:
        return None

    position = QueueTicket.objects.filter(
        created_at__date=today, served=False, queue_number__lte=ticket.queue_number
    ).count()
    wait_minutes = position * AVERAGE_CONSULTATION_MINUTES
    return {
        "queue_number": ticket.queue_number,
        "position": position,
        "estimated_wait_minutes": wait_minutes,
        "estimated_time": timezone.localtime() + timedelta(minutes=wait_minutes),
    }


def days_left_for_prescription_item(item):
    """
    Estimate remaining days of supply from the free-text `duration` field
    (e.g. "7 days", "2 weeks") and when the item was dispensed. Returns
    None if it hasn't been dispensed yet or `duration` doesn't parse —
    there's no structured duration field to compute this exactly.
    """
    if not item.dispensed or not item.dispensed_at:
        return None
    match = _DURATION_RE.search(item.duration)
    if not match:
        return None
    total_days = int(match.group(1)) * _DURATION_UNIT_DAYS[match.group(2).lower()]
    elapsed = (timezone.now().date() - item.dispensed_at.date()).days
    return max(total_days - elapsed, 0)


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


def dispense_prescription_item(item, pharmacist) -> bool:
    """
    Deduct the item's quantity from stock, earliest-expiry batch first,
    record a StockTransaction, and mark the item dispensed.

    Returns False (no changes made) if there isn't enough stock across
    all batches of the drug to cover the prescribed quantity.
    """
    with transaction.atomic():
        batches = list(
            Stock.objects.select_for_update()
            .filter(drug=item.drug, quantity__gt=0)
            .order_by("expiry_date")
        )
        if sum(batch.quantity for batch in batches) < item.quantity:
            return False

        remaining = item.quantity
        for batch in batches:
            if remaining <= 0:
                break
            take = min(batch.quantity, remaining)
            batch.quantity -= take
            batch.save(update_fields=["quantity"])
            remaining -= take

        StockTransaction.objects.create(
            drug=item.drug,
            type=StockTransaction.TransactionType.OUT,
            quantity=item.quantity,
            reason=f"Dispensed prescription item #{item.pk}",
        )
        item.dispensed = True
        item.dispensed_at = timezone.now()
        item.dispensed_by = pharmacist
        item.save(update_fields=["dispensed", "dispensed_at", "dispensed_by"])
        return True


def lab_order_fully_resulted(lab_order) -> bool:
    """True once every test ordered on this lab order has a recorded result."""
    ordered_test_ids = set(lab_order.items.values_list("test_id", flat=True))
    resulted_test_ids = set(
        LabResult.objects.filter(lab_order=lab_order).values_list("test_id", flat=True)
    )
    return ordered_test_ids <= resulted_test_ids


def visit_status_after_lab(visit) -> str:
    """Route a visit onward once the lab finishes: to pharmacy if drugs were prescribed, otherwise done."""
    if visit.prescriptions.exists():
        return Visit.Status.WAITING_PHARMACY
    return Visit.Status.COMPLETED


def refresh_invoice_totals(invoice):
    """
    Recompute total_amount from the invoice's line items and status from
    payments made so far. Call this after adding a charge or recording a
    payment — either can change what's owed or whether it's settled.
    """
    invoice.total_amount = sum(item.subtotal for item in invoice.items.all())

    if invoice.total_amount <= 0 or invoice.amount_paid <= 0:
        invoice.status = VisitInvoice.Status.UNPAID
    elif invoice.amount_paid >= invoice.total_amount:
        invoice.status = VisitInvoice.Status.PAID
    else:
        invoice.status = VisitInvoice.Status.PARTIAL

    invoice.save(update_fields=["total_amount", "status"])


def approve_refill_request(refill_request, doctor):
    """
    Approve a prescription refill: clone the source item onto a fresh Visit
    that starts life already WAITING_PHARMACY, so it flows through the
    existing pharmacy dispensing machinery unchanged — no new visit ever
    goes through a doctor consultation, since the doctor's approval here
    *is* the consultation for a refill.
    """
    source_item = refill_request.prescription_item
    with transaction.atomic():
        visit = Visit.objects.create(
            patient=refill_request.patient,
            doctor=doctor,
            department=source_item.prescription.visit.department,
            visit_type=Visit.VisitType.OPD,
            status=Visit.Status.WAITING_PHARMACY,
            symptoms="Prescription refill",
        )
        prescription = Prescription.objects.create(
            visit=visit, doctor=doctor, patient=refill_request.patient
        )
        new_item = PrescriptionItem.objects.create(
            prescription=prescription,
            drug=source_item.drug,
            quantity=source_item.quantity,
            dosage=source_item.dosage,
            frequency=source_item.frequency,
            duration=source_item.duration,
            instructions=source_item.instructions,
        )

        refill_request.status = refill_request.Status.APPROVED
        refill_request.reviewed_by = doctor
        refill_request.reviewed_at = timezone.now()
        refill_request.new_prescription_item = new_item
        refill_request.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "new_prescription_item"]
        )

    create_notification(
        refill_request.patient.user,
        "Refill approved",
        f"Your refill for {source_item.drug.name} was approved and sent to pharmacy.",
    )
    return visit


def deny_refill_request(refill_request, doctor, reason):
    refill_request.status = refill_request.Status.DENIED
    refill_request.reviewed_by = doctor
    refill_request.reviewed_at = timezone.now()
    refill_request.denial_reason = reason
    refill_request.save(update_fields=["status", "reviewed_by", "reviewed_at", "denial_reason"])

    create_notification(
        refill_request.patient.user,
        "Refill request denied",
        reason,
    )