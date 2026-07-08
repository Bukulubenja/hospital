from datetime import datetime

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .decorators import role_required
from .forms import (
    AppointmentForm,
    LabOrderItemForm,
    MedicalRecordForm,
    PatientForm,
    PrescriptionItemForm,
    VitalSignsForm,
)
from .models import (
    Appointment,
    LabOrder,
    LabOrderItem,
    Patient,
    Prescription,
    PrescriptionItem,
    QueueTicket,
    Stock,
    Visit,
)
from .permissions import can_doctor_access
from .services import dispense_prescription_item, visit_status_after_consultation

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


nurse_dashboard = _make_dashboard_view("NURSE", "dashboards/nurse_dashboard.html")
lab_dashboard = _make_dashboard_view("LAB", "dashboards/lab.html")
cashier_dashboard = _make_dashboard_view("CASHIER", "dashboards/cashier.html")
admin_dashboard = _make_dashboard_view("ADMIN", "dashboards/admin.html")
patient_dashboard = _make_dashboard_view("PATIENT", "dashboards/patient_dashboard.html")
stock_dashboard = _make_dashboard_view("STOCK_MANAGER", "dashboards/stock.html")
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