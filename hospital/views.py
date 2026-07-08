from datetime import datetime

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .decorators import role_required
from .forms import AppointmentForm, PatientForm
from .models import Appointment, Patient, QueueTicket, Visit

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


doctor_dashboard = _make_dashboard_view("DOCTOR", "dashboards/doctor_dashboard.html")
nurse_dashboard = _make_dashboard_view("NURSE", "dashboards/nurse_dashboard.html")
lab_dashboard = _make_dashboard_view("LAB", "dashboards/lab.html")
pharmacy_dashboard = _make_dashboard_view("PHARMACIST", "dashboards/pharmacy.html")
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