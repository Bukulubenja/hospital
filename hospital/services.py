# services.py

from django.db import transaction
from django.utils import timezone

from .models import ServiceGate, Stock, StockTransaction, Visit


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