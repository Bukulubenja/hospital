# services.py

from django.db import transaction
from django.utils import timezone

from .models import LabResult, ServiceGate, Stock, StockTransaction, Visit, VisitInvoice


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