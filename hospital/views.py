from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .decorators import role_required
from .forms import (
    AppointmentForm,
    InvoiceItemForm,
    LabOrderItemForm,
    LabResultForm,
    MedicalRecordForm,
    PatientForm,
    PaymentForm,
    PrescriptionItemForm,
    ReceiveStockForm,
    StockAdjustmentForm,
    VitalSignsForm,
)
from .models import (
    Appointment,
    Drug,
    InvoiceItem,
    LabOrder,
    LabOrderItem,
    LabResult,
    Patient,
    Prescription,
    PrescriptionItem,
    QueueTicket,
    Stock,
    StockTransaction,
    Visit,
    VisitInvoice,
    VitalSigns,
)
from .permissions import can_doctor_access, can_nurse_access
from .services import (
    dispense_prescription_item,
    lab_order_fully_resulted,
    refresh_invoice_totals,
    visit_status_after_consultation,
    visit_status_after_lab,
)


def _flash_form_errors(request, form, fallback="Could not save — check the values entered."):
    """Surface each of an invalid form's field/non-field errors as a message, so
    the user sees *why* it failed instead of a generic rejection."""
    errors = [error for field_errors in form.errors.values() for error in field_errors]
    for error in errors:
        messages.error(request, error)
    if not errors:
        messages.error(request, fallback)


# Single source of truth for where each role lands after login.
# Reused by both login_view and post_login_redirect so they can never
# drift out of sync with each other.
ROLE_REDIRECTS = {
    "DOCTOR": "doctor_dashboard",
    "NURSE": "nurse_dashboard",
    "RECEPTIONIST": "reception_dashboard",
    "LAB": "lab_dashboard",
    "PHARMACIST": "pharmacy_dashboard",
    "CASHIER": "cashier_dashboard",
    "ADMIN": "admin_dashboard",
    "PATIENT": "patient_dashboard",
    "STOCK_MANAGER": "stock_dashboard",
}

DEFAULT_REDIRECT = "login"


def _redirect_for_role(user):
    """Resolve the correct dashboard URL name for a given user's role."""
    role = getattr(user, "role", None)
    return redirect(ROLE_REDIRECTS.get(role, DEFAULT_REDIRECT))


def login_view(request):
    if request.user.is_authenticated:
        return _redirect_for_role(request.user)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:
            messages.error(request, "Please enter both username and password.")
            return render(request, "login.html")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return _redirect_for_role(user)

        messages.error(request, "Invalid login details")

    return render(request, "login.html")


def post_login_redirect(request):
    if not request.user.is_authenticated:
        return redirect(DEFAULT_REDIRECT)

    return _redirect_for_role(request.user)


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect(DEFAULT_REDIRECT)


# ---------------------------------------------------------------------
# Role dashboards
# ---------------------------------------------------------------------
# All dashboards follow the same pattern (require login + a specific
# role, then render that role's template), so they're generated from
# one factory instead of eight near-identical function bodies.

def _make_dashboard_view(role, template_name):
    @login_required
    @role_required(role)
    def dashboard_view(request):
        return render(request, template_name)

    dashboard_view.__name__ = f"{role.lower()}_dashboard"
    return dashboard_view


admin_dashboard = _make_dashboard_view("ADMIN", "dashboards/admin.html")
patient_dashboard = _make_dashboard_view("PATIENT", "dashboards/patient_dashboard.html")
prescription_refill = _make_dashboard_view("PHARMACIST", "dashboards/prescription_refill.html")
telemedicine_start = _make_dashboard_view("DOCTOR", "dashboards/telemedicine_start.html")
telemedicine_chat = _make_dashboard_view("DOCTOR", "dashboards/telemedicine_chat.html")
telemedicine_history = _make_dashboard_view("DOCTOR", "dashboards/telemedicine_history.html")
records_download = _make_dashboard_view("ADMIN", "dashboards/records_download.html")
lab_result_list = _make_dashboard_view("LAB", "dashboards/lab_result_list.html")
invoice_list = _make_dashboard_view("CASHIER", "dashboards/invoice_list.html")


# ---------------------------------------------------------------------
# Reception workflow: register patient -> book appointment -> check in
# ---------------------------------------------------------------------

def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@role_required("RECEPTIONIST")
def reception_dashboard(request):
    today = timezone.localdate()

    todays_appointments = (
        Appointment.objects.select_related("patient", "doctor", "department")
        .filter(appointment_date__date=today)
        .exclude(status=Appointment.Status.CANCELLED)
        .annotate(is_checked_in=Exists(Visit.objects.filter(appointment=OuterRef("pk"))))
        .order_by("appointment_date")
    )
    active_queue = (
        QueueTicket.objects.select_related("visit__patient", "visit__doctor")
        .filter(created_at__date=today, served=False)
        .order_by("queue_number")
    )

    context = {
        "todays_appointments": todays_appointments,
        "active_queue": active_queue,
        "waiting_count": active_queue.count(),
        "todays_count": todays_appointments.count(),
    }
    return render(request, "dashboards/reception.html", context)


@role_required("RECEPTIONIST")
def patient_list(request):
    query = request.GET.get("q", "").strip()
    patients = Patient.objects.all()
    if query:
        patients = patients.filter(
            Q(full_name__icontains=query)
            | Q(patient_number__icontains=query)
            | Q(phone__icontains=query)
        )
    return render(
        request, "dashboards/patient_list.html", {"patients": patients[:50], "query": query}
    )


@role_required("RECEPTIONIST")
def patient_create(request):
    if request.method == "POST":
        form = PatientForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                patient = form.save(commit=False)
                patient.save()
                patient.patient_number = f"P-{patient.pk:06d}"
                patient.save(update_fields=["patient_number"])

            messages.success(request, f"{patient.full_name} registered as {patient.patient_number}.")
            return redirect(f"{reverse('appointment_create')}?patient={patient.pk}")
    else:
        form = PatientForm()

    return render(request, "dashboards/patient_create.html", {"form": form})


@role_required("RECEPTIONIST")
def appointment_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    date_str = request.GET.get("date", "")
    parsed_date = _parse_date(date_str)

    appointments = Appointment.objects.select_related("patient", "doctor", "department").annotate(
        is_checked_in=Exists(Visit.objects.filter(appointment=OuterRef("pk")))
    )

    if query:
        appointments = appointments.filter(
            Q(patient__full_name__icontains=query) | Q(patient__patient_number__icontains=query)
        )
    if status:
        appointments = appointments.filter(status=status)
    if parsed_date:
        appointments = appointments.filter(appointment_date__date=parsed_date)

    context = {
        "appointments": appointments[:100],
        "query": query,
        "status": status,
        "date": date_str,
        "status_choices": Appointment.Status.choices,
    }
    return render(request, "dashboards/appointment_list.html", context)


@role_required("RECEPTIONIST")
def appointment_create(request):
    initial = {}
    patient_id = request.GET.get("patient")
    if patient_id:
        initial["patient"] = patient_id

    if request.method == "POST":
        form = AppointmentForm(request.POST)
        if form.is_valid():
            appointment = form.save()
            messages.success(
                request,
                f"Appointment booked for {appointment.patient.full_name} on "
                f"{appointment.appointment_date:%Y-%m-%d %H:%M}.",
            )
            return redirect("appointment_list")
    else:
        form = AppointmentForm(initial=initial)

    return render(request, "dashboards/appointment_create.html", {"form": form})


@role_required("RECEPTIONIST")
def appointment_checkin(request, pk):
    if request.method != "POST":
        return redirect("reception_dashboard")

    appointment = get_object_or_404(Appointment, pk=pk)

    if appointment.status != Appointment.Status.SCHEDULED:
        messages.error(request, "Only scheduled appointments can be checked in.")
        return redirect("reception_dashboard")

    if Visit.objects.filter(appointment=appointment).exists():
        messages.error(request, "This appointment has already been checked in.")
        return redirect("reception_dashboard")

    today = timezone.localdate()
    with transaction.atomic():
        last_ticket = (
            QueueTicket.objects.select_for_update()
            .filter(created_at__date=today)
            .order_by("-queue_number")
            .first()
        )
        next_number = (last_ticket.queue_number + 1) if last_ticket else 1

        visit = Visit.objects.create(
            appointment=appointment,
            patient=appointment.patient,
            doctor=appointment.doctor,
            department=appointment.department,
            visit_type=Visit.VisitType.OPD,
            status=Visit.Status.WAITING_DOCTOR,
            symptoms=appointment.reason,
        )
        QueueTicket.objects.create(visit=visit, queue_number=next_number)

    messages.success(
        request, f"{appointment.patient.full_name} checked in — queue number {next_number}."
    )
    return redirect("reception_dashboard")


# ---------------------------------------------------------------------
# Doctor workflow: consult -> vitals -> diagnosis -> prescribe / order labs
# ---------------------------------------------------------------------

def _in_active_consultation(user, visit):
    return can_doctor_access(user, visit) and visit.status == Visit.Status.IN_CONSULTATION


@role_required("DOCTOR")
def doctor_dashboard(request):
    waiting_visits = (
        Visit.objects.select_related("patient")
        .filter(doctor=request.user, status=Visit.Status.WAITING_DOCTOR)
        .order_by("visit_date")
    )
    in_progress_visits = (
        Visit.objects.select_related("patient")
        .filter(doctor=request.user, status=Visit.Status.IN_CONSULTATION)
        .order_by("visit_date")
    )
    context = {
        "waiting_visits": waiting_visits,
        "in_progress_visits": in_progress_visits,
    }
    return render(request, "dashboards/doctor_dashboard.html", context)


@role_required("DOCTOR")
def visit_detail(request, pk):
    visit = get_object_or_404(
        Visit.objects.select_related("patient", "doctor", "department"), pk=pk
    )
    if visit.doctor_id != request.user.id:
        raise PermissionDenied("You do not have access to this visit.")

    context = {
        "visit": visit,
        "vitals": visit.vital_signs.all(),
        "medical_records": visit.medical_records.all(),
        "prescription": visit.prescriptions.select_related(None).prefetch_related("items__drug").first(),
        "lab_order": visit.lab_orders.prefetch_related("items__test").first(),
        "vitals_form": VitalSignsForm(),
        "diagnosis_form": MedicalRecordForm(),
        "prescription_form": PrescriptionItemForm(),
        "lab_order_form": LabOrderItemForm(),
        "in_consultation": _in_active_consultation(request.user, visit),
    }
    return render(request, "dashboards/visit_detail.html", context)


@role_required("DOCTOR")
def visit_start(request, pk):
    if request.method != "POST":
        return redirect("visit_detail", pk=pk)

    visit = get_object_or_404(Visit, pk=pk)
    if not can_doctor_access(request.user, visit) or visit.status != Visit.Status.WAITING_DOCTOR:
        messages.error(request, "This visit cannot be started.")
        return redirect("doctor_dashboard")

    with transaction.atomic():
        visit.status = Visit.Status.IN_CONSULTATION
        visit.save(update_fields=["status"])
        QueueTicket.objects.filter(visit=visit).update(served=True)

    messages.success(request, f"Consultation started for {visit.patient.full_name}.")
    return redirect("visit_detail", pk=pk)


@role_required("DOCTOR")
def visit_record_vitals(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    if request.method == "POST" and _in_active_consultation(request.user, visit):
        form = VitalSignsForm(request.POST)
        if form.is_valid():
            vitals = form.save(commit=False)
            vitals.visit = visit
            vitals.recorded_by = request.user
            vitals.save()
            messages.success(request, "Vitals recorded.")
        else:
            messages.error(request, "Could not save vitals — check the values entered.")
    else:
        messages.error(request, "Vitals can only be recorded during an active consultation.")
    return redirect("visit_detail", pk=pk)


@role_required("DOCTOR")
def visit_record_diagnosis(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    if request.method == "POST" and _in_active_consultation(request.user, visit):
        form = MedicalRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.visit = visit
            record.patient = visit.patient
            record.doctor = request.user
            record.save()
            visit.diagnosis_summary = record.diagnosis
            visit.save(update_fields=["diagnosis_summary"])
            messages.success(request, "Diagnosis recorded.")
        else:
            messages.error(request, "Could not save diagnosis — check the values entered.")
    else:
        messages.error(request, "Diagnosis can only be recorded during an active consultation.")
    return redirect("visit_detail", pk=pk)


@role_required("DOCTOR")
def visit_add_prescription_item(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    if request.method == "POST" and _in_active_consultation(request.user, visit):
        form = PrescriptionItemForm(request.POST)
        if form.is_valid():
            prescription, _created = Prescription.objects.get_or_create(
                visit=visit,
                defaults={"doctor": request.user, "patient": visit.patient},
            )
            item = form.save(commit=False)
            item.prescription = prescription
            item.save()
            messages.success(request, f"{item.drug.name} added to prescription.")
        else:
            messages.error(request, "Could not add drug — check the values entered.")
    else:
        messages.error(request, "Prescriptions can only be edited during an active consultation.")
    return redirect("visit_detail", pk=pk)


@role_required("DOCTOR")
def visit_add_lab_test(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    if request.method == "POST" and _in_active_consultation(request.user, visit):
        form = LabOrderItemForm(request.POST)
        if form.is_valid():
            lab_order, _created = LabOrder.objects.get_or_create(
                visit=visit,
                defaults={"doctor": request.user, "patient": visit.patient},
            )
            test = form.cleaned_data["test"]
            _item, created = LabOrderItem.objects.get_or_create(lab_order=lab_order, test=test)
            if created:
                messages.success(request, f"{test.name} ordered.")
            else:
                messages.info(request, f"{test.name} was already ordered for this visit.")
        else:
            messages.error(request, "Could not order test — check the values entered.")
    else:
        messages.error(request, "Lab tests can only be ordered during an active consultation.")
    return redirect("visit_detail", pk=pk)


@role_required("DOCTOR")
def visit_complete(request, pk):
    if request.method != "POST":
        return redirect("visit_detail", pk=pk)

    visit = get_object_or_404(Visit, pk=pk)
    if not _in_active_consultation(request.user, visit):
        messages.error(request, "This visit cannot be completed right now.")
        return redirect("doctor_dashboard")

    visit.status = visit_status_after_consultation(visit)
    visit.save(update_fields=["status"])
    messages.success(
        request, f"Visit for {visit.patient.full_name} marked {visit.get_status_display()}."
    )
    return redirect("doctor_dashboard")


# ---------------------------------------------------------------------
# Pharmacy workflow: dispense prescriptions for visits awaiting pharmacy
# ---------------------------------------------------------------------

@role_required("PHARMACIST")
def pharmacy_dashboard(request):
    visits = (
        Visit.objects.select_related("patient")
        .filter(status=Visit.Status.WAITING_PHARMACY)
        .order_by("visit_date")
    )
    return render(request, "dashboards/pharmacy.html", {"visits": visits})


@role_required("PHARMACIST")
def prescription_detail(request, pk):
    visit = get_object_or_404(Visit.objects.select_related("patient"), pk=pk)
    if visit.status not in (Visit.Status.WAITING_PHARMACY, Visit.Status.COMPLETED):
        raise PermissionDenied("This visit is not awaiting pharmacy.")

    prescription = get_object_or_404(Prescription, visit=visit)
    items = list(prescription.items.select_related("drug").all())

    stock_by_drug = {
        row["drug"]: row["total"]
        for row in Stock.objects.filter(drug__in=[item.drug_id for item in items])
        .values("drug")
        .annotate(total=Sum("quantity"))
    }
    for item in items:
        item.available_stock = stock_by_drug.get(item.drug_id, 0)

    context = {
        "visit": visit,
        "prescription": prescription,
        "items": items,
        "can_dispense": visit.status == Visit.Status.WAITING_PHARMACY,
    }
    return render(request, "dashboards/prescription_detail.html", context)


@role_required("PHARMACIST")
def dispense_item(request, pk, item_pk):
    if request.method != "POST":
        return redirect("prescription_detail", pk=pk)

    visit = get_object_or_404(Visit, pk=pk)
    if visit.status != Visit.Status.WAITING_PHARMACY:
        messages.error(request, "This visit is not awaiting pharmacy.")
        return redirect("pharmacy_dashboard")

    item = get_object_or_404(PrescriptionItem, pk=item_pk, prescription__visit=visit)
    if item.dispensed:
        messages.info(request, f"{item.drug.name} was already dispensed.")
        return redirect("prescription_detail", pk=pk)

    if dispense_prescription_item(item, request.user):
        messages.success(request, f"Dispensed {item.drug.name} x{item.quantity}.")
        if not item.prescription.items.filter(dispensed=False).exists():
            visit.status = Visit.Status.COMPLETED
            visit.save(update_fields=["status"])
            messages.success(request, "All items dispensed — visit completed.")
    else:
        messages.error(request, f"Not enough stock to dispense {item.drug.name}.")

    return redirect("prescription_detail", pk=pk)


# ---------------------------------------------------------------------
# Lab workflow: record results for visits awaiting lab work
# ---------------------------------------------------------------------

@role_required("LAB")
def lab_dashboard(request):
    visits = (
        Visit.objects.select_related("patient")
        .filter(status=Visit.Status.WAITING_LAB)
        .order_by("visit_date")
    )
    return render(request, "dashboards/lab.html", {"visits": visits})


@role_required("LAB")
def lab_order_detail(request, pk):
    visit = get_object_or_404(Visit.objects.select_related("patient"), pk=pk)
    if visit.status not in (Visit.Status.WAITING_LAB, Visit.Status.COMPLETED):
        raise PermissionDenied("This visit is not awaiting lab work.")

    lab_order = get_object_or_404(LabOrder, visit=visit)
    items = list(lab_order.items.select_related("test").all())
    results_by_test = {
        result.test_id: result for result in LabResult.objects.filter(lab_order=lab_order)
    }
    can_record = visit.status == Visit.Status.WAITING_LAB
    for item in items:
        item.result = results_by_test.get(item.test_id)
        if item.result is None and can_record:
            item.result_form = LabResultForm(prefix=str(item.pk))

    context = {
        "visit": visit,
        "lab_order": lab_order,
        "items": items,
        "can_record": can_record,
    }
    return render(request, "dashboards/lab_order_detail.html", context)


@role_required("LAB")
def record_lab_result(request, pk, item_pk):
    if request.method != "POST":
        return redirect("lab_order_detail", pk=pk)

    visit = get_object_or_404(Visit, pk=pk)
    if visit.status != Visit.Status.WAITING_LAB:
        messages.error(request, "This visit is not awaiting lab work.")
        return redirect("lab_dashboard")

    with transaction.atomic():
        lab_order = get_object_or_404(
            LabOrder.objects.select_for_update(), visit=visit
        )
        item = get_object_or_404(LabOrderItem, pk=item_pk, lab_order=lab_order)

        if LabResult.objects.filter(lab_order=lab_order, test=item.test).exists():
            messages.info(request, f"A result for {item.test.name} was already recorded.")
            return redirect("lab_order_detail", pk=pk)

        form = LabResultForm(request.POST, prefix=str(item_pk))
        if not form.is_valid():
            messages.error(request, "Could not save result — check the values entered.")
            return redirect("lab_order_detail", pk=pk)

        result = form.save(commit=False)
        result.lab_order = lab_order
        result.test = item.test
        result.save()

        if lab_order.status == LabOrder.Status.PENDING:
            lab_order.status = LabOrder.Status.PROCESSING
            lab_order.save(update_fields=["status"])

        messages.success(request, f"Result recorded for {item.test.name}.")

        if lab_order_fully_resulted(lab_order):
            lab_order.status = LabOrder.Status.COMPLETED
            lab_order.save(update_fields=["status"])
            visit.status = visit_status_after_lab(visit)
            visit.save(update_fields=["status"])
            messages.success(
                request, f"All lab results recorded — visit marked {visit.get_status_display()}."
            )

    return redirect("lab_order_detail", pk=pk)


# ---------------------------------------------------------------------
# Cashier workflow: bill a visit and collect payment
# ---------------------------------------------------------------------

@role_required("CASHIER")
def cashier_dashboard(request):
    visits = list(
        Visit.objects.select_related("patient").order_by("-visit_date")[:50]
    )
    invoices_by_visit = {
        invoice.visit_id: invoice
        for invoice in VisitInvoice.objects.filter(visit_id__in=[v.id for v in visits])
    }
    for visit in visits:
        visit.invoice = invoices_by_visit.get(visit.id)

    return render(request, "dashboards/cashier.html", {"visits": visits})


@role_required("CASHIER")
def visit_invoice_detail(request, pk):
    visit = get_object_or_404(Visit.objects.select_related("patient"), pk=pk)
    invoice, _created = VisitInvoice.objects.get_or_create(
        visit=visit, defaults={"patient": visit.patient, "total_amount": 0}
    )

    context = {
        "visit": visit,
        "invoice": invoice,
        "items": invoice.items.select_related("service").all(),
        "payments": invoice.payments.all(),
        "item_form": InvoiceItemForm(),
        "payment_form": PaymentForm(invoice=invoice),
    }
    return render(request, "dashboards/visit_invoice_detail.html", context)


@role_required("CASHIER")
def add_invoice_item(request, pk):
    if request.method != "POST":
        return redirect("visit_invoice_detail", pk=pk)

    visit = get_object_or_404(Visit, pk=pk)
    invoice, _created = VisitInvoice.objects.get_or_create(
        visit=visit, defaults={"patient": visit.patient, "total_amount": 0}
    )

    form = InvoiceItemForm(request.POST)
    if form.is_valid():
        service = form.cleaned_data["service"]
        quantity = form.cleaned_data["quantity"]
        InvoiceItem.objects.create(
            invoice=invoice, service=service, quantity=quantity, price=service.price
        )
        refresh_invoice_totals(invoice)
        messages.success(request, f"Added {service.name} x{quantity}.")
    else:
        messages.error(request, "Could not add charge — check the values entered.")

    return redirect("visit_invoice_detail", pk=pk)


@role_required("CASHIER")
def record_payment(request, pk):
    if request.method != "POST":
        return redirect("visit_invoice_detail", pk=pk)

    visit = get_object_or_404(Visit, pk=pk)

    with transaction.atomic():
        invoice = get_object_or_404(VisitInvoice.objects.select_for_update(), visit=visit)

        if invoice.balance_due <= 0:
            messages.info(request, "This invoice is already fully paid.")
            return redirect("visit_invoice_detail", pk=pk)

        form = PaymentForm(request.POST, invoice=invoice)
        if not form.is_valid():
            _flash_form_errors(request, form, "Could not record payment — check the values entered.")
            return redirect("visit_invoice_detail", pk=pk)

        payment = form.save(commit=False)
        payment.invoice = invoice
        payment.save()
        payment.receipt_number = f"RCPT-{payment.pk:06d}"
        payment.save(update_fields=["receipt_number"])
        refresh_invoice_totals(invoice)

    messages.success(
        request, f"Payment of {payment.amount_paid} recorded — receipt {payment.receipt_number}."
    )
    return redirect("visit_invoice_detail", pk=pk)


# ---------------------------------------------------------------------
# Nurse workflow: triage patients waiting on a doctor
# ---------------------------------------------------------------------

@role_required("NURSE")
def nurse_dashboard(request):
    visits = (
        Visit.objects.select_related("patient", "doctor")
        .filter(status=Visit.Status.WAITING_DOCTOR)
        .annotate(has_vitals=Exists(VitalSigns.objects.filter(visit=OuterRef("pk"))))
        .order_by("visit_date")
    )
    return render(request, "dashboards/nurse_dashboard.html", {"visits": visits})


@role_required("NURSE")
def nurse_triage(request, pk):
    visit = get_object_or_404(Visit.objects.select_related("patient", "doctor"), pk=pk)
    if not can_nurse_access(request.user, visit):
        raise PermissionDenied("This visit is not awaiting triage.")

    context = {
        "visit": visit,
        "vitals": visit.vital_signs.all(),
        "vitals_form": VitalSignsForm(),
    }
    return render(request, "dashboards/nurse_triage.html", context)


@role_required("NURSE")
def nurse_record_vitals(request, pk):
    if request.method != "POST":
        return redirect("nurse_triage", pk=pk)

    visit = get_object_or_404(Visit, pk=pk)
    if not can_nurse_access(request.user, visit):
        messages.error(request, "This visit is not awaiting triage.")
        return redirect("nurse_dashboard")

    form = VitalSignsForm(request.POST)
    if form.is_valid():
        vitals = form.save(commit=False)
        vitals.visit = visit
        vitals.recorded_by = request.user
        vitals.save()
        messages.success(request, "Vitals recorded.")
    else:
        messages.error(request, "Could not save vitals — check the values entered.")

    return redirect("nurse_triage", pk=pk)


# ---------------------------------------------------------------------
# Stock Manager workflow: receive stock and write off spoiled/lost stock
# ---------------------------------------------------------------------

@role_required("STOCK_MANAGER")
def stock_dashboard(request):
    today = timezone.localdate()
    soon = today + timedelta(days=30)

    drugs = Drug.objects.annotate(
        total_quantity=Coalesce(Sum("stock_entries__quantity"), 0)
    ).order_by("name")

    context = {
        "drugs": drugs,
        "expiring_soon_count": Stock.objects.filter(
            quantity__gt=0, expiry_date__gte=today, expiry_date__lte=soon
        ).count(),
        "expired_count": Stock.objects.filter(quantity__gt=0, expiry_date__lt=today).count(),
        "recent_transactions": StockTransaction.objects.select_related("drug")[:20],
    }
    return render(request, "dashboards/stock.html", context)


@role_required("STOCK_MANAGER")
def drug_stock_detail(request, pk):
    drug = get_object_or_404(Drug, pk=pk)
    today = timezone.localdate()

    context = {
        "drug": drug,
        "batches": drug.stock_entries.all(),
        "transactions": drug.transactions.all()[:20],
        "today": today,
        "expiry_warning_date": today + timedelta(days=30),
        "receive_form": ReceiveStockForm(),
        "adjust_form": StockAdjustmentForm(drug=drug),
    }
    return render(request, "dashboards/drug_stock_detail.html", context)


@role_required("STOCK_MANAGER")
def receive_stock(request, pk):
    if request.method != "POST":
        return redirect("drug_stock_detail", pk=pk)

    drug = get_object_or_404(Drug, pk=pk)
    form = ReceiveStockForm(request.POST)
    if form.is_valid():
        batch_number = form.cleaned_data["batch_number"]
        quantity = form.cleaned_data["quantity"]
        expiry_date = form.cleaned_data["expiry_date"]

        with transaction.atomic():
            stock, created = Stock.objects.select_for_update().get_or_create(
                drug=drug,
                batch_number=batch_number,
                defaults={"quantity": quantity, "expiry_date": expiry_date},
            )
            if not created:
                stock.quantity += quantity
                stock.save(update_fields=["quantity"])

            StockTransaction.objects.create(
                drug=drug,
                type=StockTransaction.TransactionType.IN,
                quantity=quantity,
                reason=f"Received batch {batch_number}",
            )

        messages.success(
            request, f"Received {quantity} units of {drug.name} (batch {batch_number})."
        )
    else:
        _flash_form_errors(request, form, "Could not receive stock — check the values entered.")

    return redirect("drug_stock_detail", pk=pk)


@role_required("STOCK_MANAGER")
def adjust_stock(request, pk):
    if request.method != "POST":
        return redirect("drug_stock_detail", pk=pk)

    drug = get_object_or_404(Drug, pk=pk)
    form = StockAdjustmentForm(request.POST, drug=drug)
    if form.is_valid():
        quantity = form.cleaned_data["quantity"]
        reason = form.cleaned_data["reason"]

        with transaction.atomic():
            batch = Stock.objects.select_for_update().get(pk=form.cleaned_data["batch"].pk)
            if quantity > batch.quantity:
                messages.error(
                    request,
                    f"Cannot remove {quantity} units — only {batch.quantity} left in batch {batch.batch_number}.",
                )
                return redirect("drug_stock_detail", pk=pk)

            batch.quantity -= quantity
            batch.save(update_fields=["quantity"])
            StockTransaction.objects.create(
                drug=drug, type=StockTransaction.TransactionType.OUT,
                quantity=quantity, reason=reason,
            )

        messages.success(request, f"Removed {quantity} units from batch {batch.batch_number}.")
    else:
        _flash_form_errors(request, form, "Could not adjust stock — check the values entered.")

    return redirect("drug_stock_detail", pk=pk)