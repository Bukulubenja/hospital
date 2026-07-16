import json
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import JsonResponse
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
    MeetingLinkForm,
    MessageComposeForm,
    MessageReplyForm,
    PatientForm,
    PatientTelemedicineForm,
    PaymentForm,
    PrescriptionItemForm,
    ReceiveStockForm,
    StockAdjustmentForm,
    VitalSignsForm,
)
from .models import (
    Appointment,
    Bed,
    Department,
    Drug,
    EmergencyAlert,
    InvoiceItem,
    LabOrder,
    LabOrderItem,
    LabResult,
    MedicalRecord,
    Message,
    Notification,
    Patient,
    Payment,
    Prescription,
    PrescriptionItem,
    QueueTicket,
    RefillRequest,
    Stock,
    StockTransaction,
    User,
    Visit,
    VisitInvoice,
    VitalSigns,
    Ward,
)
from .permissions import can_doctor_access, can_nurse_access
from .services import (
    approve_refill_request,
    create_notification,
    days_left_for_prescription_item,
    deny_refill_request,
    dispense_prescription_item,
    lab_order_fully_resulted,
    patient_for_user,
    queue_snapshot_for_patient,
    record_audit_log,
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


def _client_ip(request):
    """Best-effort client IP for AuditLog rows — the leftmost X-Forwarded-For
    entry if behind a proxy, else REMOTE_ADDR."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


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
            if request.POST.get("remember_me"):
                request.session.set_expiry(1209600)  # persist 2 weeks
            else:
                request.session.set_expiry(0)  # expire when the browser closes
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
    active_emergency_alerts = EmergencyAlert.objects.select_related("patient").exclude(
        status=EmergencyAlert.Status.RESOLVED
    )

    context = {
        "todays_appointments": todays_appointments,
        "active_queue": active_queue,
        "waiting_count": active_queue.count(),
        "todays_count": todays_appointments.count(),
        "active_emergency_alerts": active_emergency_alerts,
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


@role_required("RECEPTIONIST")
def set_meeting_link(request, pk):
    if request.method != "POST":
        return redirect("appointment_list")

    appointment = get_object_or_404(Appointment, pk=pk)
    if appointment.consultation_type != Appointment.ConsultationType.TELEMEDICINE:
        messages.error(request, "Only telemedicine appointments have a meeting link.")
        return redirect("appointment_list")

    form = MeetingLinkForm(request.POST)
    if form.is_valid():
        appointment.meeting_link = form.cleaned_data["meeting_link"]
        appointment.save(update_fields=["meeting_link"])
        messages.success(request, f"Meeting link set for {appointment.patient.full_name}.")
    else:
        _flash_form_errors(request, form, "Could not save the meeting link.")

    return redirect("appointment_list")


@role_required("RECEPTIONIST")
def emergency_alert_acknowledge(request, pk):
    if request.method != "POST":
        return redirect("reception_dashboard")

    alert = get_object_or_404(EmergencyAlert, pk=pk)
    if alert.status != EmergencyAlert.Status.NEW:
        messages.error(request, "This alert was already acknowledged.")
        return redirect("reception_dashboard")

    alert.status = EmergencyAlert.Status.ACKNOWLEDGED
    alert.acknowledged_by = request.user
    alert.acknowledged_at = timezone.now()
    alert.save(update_fields=["status", "acknowledged_by", "acknowledged_at"])
    record_audit_log(request.user, "ACKNOWLEDGE_EMERGENCY_ALERT", alert, ip_address=_client_ip(request))
    messages.success(request, f"Alert for {alert.patient.full_name} acknowledged.")
    return redirect("reception_dashboard")


@role_required("RECEPTIONIST")
def emergency_alert_resolve(request, pk):
    if request.method != "POST":
        return redirect("reception_dashboard")

    alert = get_object_or_404(EmergencyAlert, pk=pk)
    if alert.status == EmergencyAlert.Status.RESOLVED:
        messages.error(request, "This alert is already resolved.")
        return redirect("reception_dashboard")

    alert.status = EmergencyAlert.Status.RESOLVED
    alert.save(update_fields=["status"])
    record_audit_log(request.user, "RESOLVE_EMERGENCY_ALERT", alert, ip_address=_client_ip(request))
    messages.success(request, f"Alert for {alert.patient.full_name} marked resolved.")
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
    pending_refill_requests = (
        RefillRequest.objects.select_related("patient", "prescription_item__drug")
        .filter(status=RefillRequest.Status.PENDING, prescription_item__prescription__doctor=request.user)
        .order_by("requested_at")
    )
    unread_message_count = (
        Message.objects.filter(doctor=request.user, is_read=False).exclude(sender=request.user).count()
    )
    context = {
        "waiting_visits": waiting_visits,
        "in_progress_visits": in_progress_visits,
        "pending_refill_requests": pending_refill_requests,
        "unread_message_count": unread_message_count,
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
            record_audit_log(request.user, "RECORD_DIAGNOSIS", record, ip_address=_client_ip(request))
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


def _owns_refill_request(user, refill_request):
    return refill_request.prescription_item.prescription.doctor_id == user.id


@role_required("DOCTOR")
def refill_request_approve(request, pk):
    if request.method != "POST":
        return redirect("doctor_dashboard")

    refill_request = get_object_or_404(RefillRequest, pk=pk)
    if not _owns_refill_request(request.user, refill_request):
        raise PermissionDenied("You do not have access to this refill request.")
    if refill_request.status != RefillRequest.Status.PENDING:
        messages.error(request, "This refill request has already been reviewed.")
        return redirect("doctor_dashboard")

    approve_refill_request(refill_request, request.user)
    record_audit_log(request.user, "APPROVE_REFILL_REQUEST", refill_request, ip_address=_client_ip(request))
    messages.success(
        request,
        f"Refill approved for {refill_request.patient.full_name} — sent to pharmacy.",
    )
    return redirect("doctor_dashboard")


@role_required("DOCTOR")
def refill_request_deny(request, pk):
    if request.method != "POST":
        return redirect("doctor_dashboard")

    refill_request = get_object_or_404(RefillRequest, pk=pk)
    if not _owns_refill_request(request.user, refill_request):
        raise PermissionDenied("You do not have access to this refill request.")
    if refill_request.status != RefillRequest.Status.PENDING:
        messages.error(request, "This refill request has already been reviewed.")
        return redirect("doctor_dashboard")

    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "A reason is required to deny a refill request.")
        return redirect("doctor_dashboard")

    deny_refill_request(refill_request, request.user, reason)
    record_audit_log(request.user, "DENY_REFILL_REQUEST", refill_request, ip_address=_client_ip(request))
    messages.success(request, f"Refill request for {refill_request.patient.full_name} denied.")
    return redirect("doctor_dashboard")


@role_required("DOCTOR")
def doctor_messages(request):
    patient_ids = Message.objects.filter(doctor=request.user).values_list("patient_id", flat=True).distinct()
    patients = Patient.objects.filter(pk__in=patient_ids)

    conversations = []
    for patient in patients:
        thread = Message.objects.filter(doctor=request.user, patient=patient).order_by("-created_at")
        latest = thread.first()
        unread = thread.filter(is_read=False).exclude(sender=request.user).count()
        conversations.append({"patient": patient, "latest": latest, "unread": unread})
    conversations.sort(key=lambda c: c["latest"].created_at, reverse=True)

    return render(request, "dashboards/doctor_messages.html", {"conversations": conversations})


@role_required("DOCTOR")
def doctor_message_thread(request, patient_pk):
    patient = get_object_or_404(Patient, pk=patient_pk)
    if not Visit.objects.filter(doctor=request.user, patient=patient).exists():
        raise PermissionDenied("You can only message patients you have treated.")

    if request.method == "POST":
        form = MessageReplyForm(request.POST)
        if form.is_valid():
            Message.objects.create(
                patient=patient, doctor=request.user, sender=request.user, body=form.cleaned_data["body"]
            )
            create_notification(
                patient.user,
                f"New message from Dr. {request.user.get_full_name() or request.user.username}",
                form.cleaned_data["body"][:200],
            )
            messages.success(request, "Message sent.")
        else:
            _flash_form_errors(request, form, "Could not send the message.")
        return redirect("doctor_message_thread", patient_pk=patient.pk)

    thread = Message.objects.filter(doctor=request.user, patient=patient).order_by("created_at")
    thread.exclude(sender=request.user).filter(is_read=False).update(is_read=True)

    return render(
        request,
        "dashboards/doctor_message_thread.html",
        {"patient": patient, "thread": thread, "form": MessageReplyForm()},
    )


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
        record_audit_log(request.user, "DISPENSE_PRESCRIPTION_ITEM", item, ip_address=_client_ip(request))
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
        record_audit_log(request.user, "RECORD_LAB_RESULT", result, ip_address=_client_ip(request))

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
        record_audit_log(request.user, "RECORD_PAYMENT", payment, ip_address=_client_ip(request))
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


# ---------------------------------------------------------------------
# Patient workflow: dashboard, telemedicine requests, prescription
# refills, records download. Every view here resolves the caller's own
# Patient record via patient_for_user() and scopes all queries to it —
# there's no shared queue to gate like doctor/nurse, so a plain query
# filter is the only access control needed.
# ---------------------------------------------------------------------

@role_required("PATIENT")
def patient_dashboard(request):
    patient = patient_for_user(request.user)
    if patient is None:
        return render(request, "dashboards/patient_dashboard.html", {"patient": None})

    now = timezone.now()
    last_visit = patient.visits.order_by("-visit_date").first()
    invoices = list(VisitInvoice.objects.filter(patient=patient))
    total_paid = sum((invoice.amount_paid for invoice in invoices), Decimal("0"))
    total_due = sum((invoice.balance_due for invoice in invoices), Decimal("0"))

    active_prescription_items = list(
        PrescriptionItem.objects.filter(prescription__patient=patient, dispensed=True)
        .select_related("drug", "prescription")
        .order_by("-prescription__created_at")[:10]
    )
    for item in active_prescription_items:
        item.days_left = days_left_for_prescription_item(item)

    notifications_qs = Notification.objects.filter(user=request.user).order_by("-created_at")
    recent_notifications = list(notifications_qs[:5])
    unread_notification_count = notifications_qs.filter(is_read=False).count()

    recent_messages = list(
        Message.objects.filter(patient=patient)
        .select_related("doctor", "sender")
        .order_by("-created_at")[:5]
    )
    for item in recent_messages:
        item.sender_name = (
            "You"
            if item.sender_id == request.user.id
            else f"Dr. {item.doctor.get_full_name() or item.doctor.username}"
        )
        item.sent_at = item.created_at
        item.preview = item.body[:120]

    context = {
        "patient": patient,
        "last_visit": last_visit,
        "latest_visit_summary": last_visit.diagnosis_summary if last_visit else "",
        "upcoming_appointments": (
            patient.appointments.select_related("doctor", "department")
            .filter(appointment_date__gte=now, status=Appointment.Status.SCHEDULED)
            .order_by("appointment_date")
        ),
        "latest_vitals": VitalSigns.objects.filter(visit__patient=patient)
        .order_by("-recorded_at")
        .first(),
        "recent_lab_results": LabResult.objects.filter(lab_order__patient=patient)
        .select_related("test", "lab_order")
        .order_by("-result_date")[:5],
        "departments": Department.objects.all(),
        "medical_history": MedicalRecord.objects.filter(patient=patient)
        .select_related("doctor", "visit")
        .order_by("-created_at")[:10],
        "active_prescription_items": active_prescription_items,
        "recent_refill_requests": patient.refill_requests.select_related(
            "prescription_item__drug"
        )[:5],
        "total_paid": total_paid,
        # No separate "overdue" concept in the data model yet — pending and
        # due both currently mean "outstanding balance across all invoices".
        "total_pending": total_due,
        "total_due": total_due,
        "recent_invoices": VisitInvoice.objects.filter(patient=patient).order_by("-created_at")[:5],
        "recent_notifications": recent_notifications,
        "unread_notification_count": unread_notification_count,
        "recent_messages": recent_messages,
        "queue_snapshot": queue_snapshot_for_patient(patient),
    }
    return render(request, "dashboards/patient_dashboard.html", context)


@role_required("PATIENT")
def patient_appointment_cancel(request, pk):
    if request.method != "POST":
        return redirect("patient_dashboard")

    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    appointment = get_object_or_404(Appointment, pk=pk, patient=patient)
    if appointment.status != Appointment.Status.SCHEDULED:
        messages.error(request, "Only scheduled appointments can be cancelled.")
        return redirect("patient_dashboard")

    appointment.status = Appointment.Status.CANCELLED
    appointment.save(update_fields=["status"])
    messages.success(request, "Appointment cancelled.")
    return redirect("patient_dashboard")


@role_required("PATIENT")
def notifications_mark_all_read(request):
    if request.method != "POST":
        return redirect("patient_dashboard")

    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("patient_dashboard")


@role_required("PATIENT")
def emergency_alert_create(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    patient = patient_for_user(request.user)
    if patient is None:
        return JsonResponse(
            {"error": "Your account isn't linked to a patient record yet."}, status=400
        )

    try:
        payload = json.loads(request.body)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    severity = payload.get("severity")
    if severity not in EmergencyAlert.Severity.values:
        return JsonResponse({"error": "Select a valid severity level."}, status=400)

    share_location = bool(payload.get("share_location"))
    latitude = payload.get("latitude") if share_location else None
    longitude = payload.get("longitude") if share_location else None

    EmergencyAlert.objects.create(
        patient=patient,
        severity=severity,
        details=(payload.get("details") or "").strip(),
        latitude=latitude,
        longitude=longitude,
    )
    return JsonResponse({"ok": True})


@role_required("PATIENT")
def patient_change_password(request):
    if request.method != "POST":
        return redirect(f"{reverse('patient_dashboard')}#settings")

    form = PasswordChangeForm(user=request.user, data=request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # keep the current session logged in
        messages.success(request, "Password changed.")
    else:
        _flash_form_errors(request, form, "Could not change password.")

    return redirect(f"{reverse('patient_dashboard')}#settings")


@role_required("PATIENT")
def patient_messages(request):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    available_doctors = (
        User.objects.filter(role=User.Role.DOCTOR, visits_as_doctor__patient=patient)
        .distinct()
        .order_by("first_name", "last_name")
    )

    if request.method == "POST":
        form = MessageComposeForm(request.POST, doctor_queryset=available_doctors)
        if form.is_valid():
            doctor = form.cleaned_data["doctor"]
            Message.objects.create(
                patient=patient, doctor=doctor, sender=request.user, body=form.cleaned_data["body"]
            )
            create_notification(doctor, f"New message from {patient.full_name}", form.cleaned_data["body"][:200])
            messages.success(request, "Message sent.")
            return redirect("patient_messages")
        _flash_form_errors(request, form, "Could not send the message.")
    else:
        form = MessageComposeForm(doctor_queryset=available_doctors)

    conversations = []
    for doctor in available_doctors:
        thread = Message.objects.filter(patient=patient, doctor=doctor).order_by("-created_at")
        latest = thread.first()
        unread = thread.filter(is_read=False).exclude(sender=request.user).count()
        conversations.append({"doctor": doctor, "latest": latest, "unread": unread})

    context = {
        "patient": patient,
        "form": form,
        "available_doctors": available_doctors,
        "conversations": conversations,
    }
    return render(request, "dashboards/patient_messages.html", context)


@role_required("PATIENT")
def patient_message_thread(request, doctor_pk):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    doctor = get_object_or_404(User, pk=doctor_pk, role=User.Role.DOCTOR)
    if not Visit.objects.filter(doctor=doctor, patient=patient).exists():
        raise PermissionDenied("You can only message a doctor who has treated you.")

    if request.method == "POST":
        form = MessageReplyForm(request.POST)
        if form.is_valid():
            Message.objects.create(
                patient=patient, doctor=doctor, sender=request.user, body=form.cleaned_data["body"]
            )
            create_notification(
                doctor, f"New message from {patient.full_name}", form.cleaned_data["body"][:200]
            )
            messages.success(request, "Message sent.")
        else:
            _flash_form_errors(request, form, "Could not send the message.")
        return redirect("patient_message_thread", doctor_pk=doctor.pk)

    thread = Message.objects.filter(patient=patient, doctor=doctor).order_by("created_at")
    thread.exclude(sender=request.user).filter(is_read=False).update(is_read=True)

    return render(
        request,
        "dashboards/patient_message_thread.html",
        {"patient": patient, "doctor": doctor, "thread": thread, "form": MessageReplyForm()},
    )


@role_required("PATIENT")
def prescription_refill(request):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    eligible_items = (
        PrescriptionItem.objects.filter(prescription__patient=patient, dispensed=True)
        .select_related("drug", "prescription")
        .annotate(
            has_pending_request=Exists(
                RefillRequest.objects.filter(
                    prescription_item=OuterRef("pk"), status=RefillRequest.Status.PENDING
                )
            )
        )
        .order_by("-prescription__created_at")
    )
    refill_requests = patient.refill_requests.select_related(
        "prescription_item__drug", "reviewed_by"
    )

    context = {
        "patient": patient,
        "eligible_items": eligible_items,
        "refill_requests": refill_requests,
    }
    return render(request, "dashboards/prescription_refill.html", context)


@role_required("PATIENT")
def request_refill(request, item_pk):
    if request.method != "POST":
        return redirect("prescription_refill")

    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    item = get_object_or_404(
        PrescriptionItem, pk=item_pk, prescription__patient=patient, dispensed=True
    )
    if RefillRequest.objects.filter(
        prescription_item=item, status=RefillRequest.Status.PENDING
    ).exists():
        messages.error(request, f"You already have a pending refill request for {item.drug.name}.")
        return redirect("prescription_refill")

    RefillRequest.objects.create(patient=patient, prescription_item=item)
    messages.success(request, f"Refill requested for {item.drug.name} — awaiting doctor approval.")
    return redirect("prescription_refill")


@role_required("PATIENT")
def telemedicine_start(request):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    if request.method == "POST":
        form = PatientTelemedicineForm(request.POST)
        if form.is_valid():
            appointment = form.save(commit=False)
            appointment.patient = patient
            appointment.consultation_type = Appointment.ConsultationType.TELEMEDICINE
            appointment.save()
            messages.success(
                request,
                f"Telemedicine visit requested for {appointment.appointment_date:%Y-%m-%d %H:%M}. "
                "Reception will add your video call link before the appointment.",
            )
            return redirect("telemedicine_start")
        _flash_form_errors(request, form, "Could not request the appointment.")
    else:
        form = PatientTelemedicineForm()

    upcoming = (
        patient.appointments.select_related("doctor", "department")
        .filter(
            consultation_type=Appointment.ConsultationType.TELEMEDICINE,
            status=Appointment.Status.SCHEDULED,
        )
        .order_by("appointment_date")
    )
    context = {"patient": patient, "form": form, "upcoming_appointments": upcoming}
    return render(request, "dashboards/telemedicine_start.html", context)


@role_required("PATIENT")
def telemedicine_history(request):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    past_appointments = (
        patient.appointments.select_related("doctor", "department")
        .filter(consultation_type=Appointment.ConsultationType.TELEMEDICINE)
        .exclude(status=Appointment.Status.SCHEDULED)
        .order_by("-appointment_date")
    )
    return render(
        request,
        "dashboards/telemedicine_history.html",
        {"patient": patient, "past_appointments": past_appointments},
    )


@role_required("PATIENT")
def records_download(request):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    context = {
        "patient": patient,
        "visits": patient.visits.select_related("doctor", "department").order_by("-visit_date"),
        "medical_records": MedicalRecord.objects.filter(patient=patient)
        .select_related("doctor", "visit")
        .order_by("-created_at"),
        "prescriptions": Prescription.objects.filter(patient=patient)
        .prefetch_related("items__drug")
        .order_by("-created_at"),
        "lab_orders": LabOrder.objects.filter(patient=patient)
        .prefetch_related("items__test", "results__test")
        .order_by("-created_at"),
        "generated_at": timezone.now(),
    }
    return render(request, "dashboards/records_download.html", context)


@role_required("PATIENT")
def lab_result_list(request):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    results = (
        LabResult.objects.filter(lab_order__patient=patient)
        .select_related("test", "lab_order")
        .order_by("-result_date")
    )
    return render(request, "dashboards/lab_result_list.html", {"patient": patient, "results": results})


@role_required("PATIENT")
def invoice_list(request):
    patient = patient_for_user(request.user)
    if patient is None:
        messages.error(request, "Your account isn't linked to a patient record yet.")
        return redirect("patient_dashboard")

    invoices = (
        VisitInvoice.objects.filter(patient=patient)
        .prefetch_related("items__service", "payments")
        .order_by("-created_at")
    )
    return render(request, "dashboards/invoice_list.html", {"patient": patient, "invoices": invoices})


# ---------------------------------------------------------------------
# Admin dashboard: hospital-wide KPIs, trends, and operational overview
# ---------------------------------------------------------------------
#
# Chart geometry (bar/line coordinates, SVG path strings) is computed here
# in Python rather than in the template: Django templates have no general
# arithmetic, and hand-deriving pixel math in template tags is unreadable
# and easy to get subtly wrong. The template only formats and positions
# pre-computed numbers.

CHART_WIDTH = 700
CHART_PLOT_TOP = 16
CHART_BASELINE = 184
CHART_HEIGHT = 224
CHART_BAR_WIDTH = 24


def _rounded_top_bar_path(x, y, width, height, radius=4):
    """SVG path for a bar: rounded top corners, square bottom (sits on the baseline)."""
    if height <= 0:
        return ""
    r = min(radius, height / 2, width / 2)
    if r <= 0:
        return f"M {x},{y + height} L {x},{y} L {x + width},{y} L {x + width},{y + height} Z"
    return (
        f"M {x},{y + height} "
        f"L {x},{y + r} "
        f"Q {x},{y} {x + r},{y} "
        f"L {x + width - r},{y} "
        f"Q {x + width},{y} {x + width},{y + r} "
        f"L {x + width},{y + height} Z"
    )


def _build_bar_chart(items, value_key="value", bar_width=CHART_BAR_WIDTH, max_bars=None):
    """Turn a list of {label/date, <value_key>} dicts into bar geometry for inline SVG."""
    if max_bars:
        items = items[:max_bars]

    plot_height = CHART_BASELINE - CHART_PLOT_TOP
    max_value = max((item[value_key] for item in items), default=0) or 1
    n = len(items)
    slot_width = CHART_WIDTH / n if n else CHART_WIDTH

    bars = []
    for i, item in enumerate(items):
        value = item[value_key]
        height = round((value / max_value) * plot_height) if max_value else 0
        x = round(i * slot_width + (slot_width - bar_width) / 2)
        y = CHART_BASELINE - height
        bars.append({
            **item,
            "x": x,
            "y": y,
            "width": bar_width,
            "height": height,
            "path": _rounded_top_bar_path(x, y, bar_width, height),
            "label_x": round(x + bar_width / 2),
        })
    return {
        "bars": bars,
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "baseline": CHART_BASELINE,
        "max_value": max_value,
    }


def _build_line_chart(series):
    """Turn a list of {date, value} dicts into line/area geometry for inline SVG."""
    plot_height = CHART_BASELINE - CHART_PLOT_TOP
    max_value = max((float(point["value"]) for point in series), default=0) or 1
    n = len(series)
    slot_width = CHART_WIDTH / (n - 1) if n > 1 else 0

    points = []
    for i, point in enumerate(series):
        value = float(point["value"])
        height = (value / max_value) * plot_height if max_value else 0
        x = round(i * slot_width) if n > 1 else CHART_WIDTH / 2
        y = round(CHART_BASELINE - height)
        points.append({"date": point["date"], "value": point["value"], "x": x, "y": y})

    path = "M " + " L ".join(f"{p['x']},{p['y']}" for p in points) if points else ""
    area_path = ""
    if points:
        area_path = (
            path
            + f" L {points[-1]['x']},{CHART_BASELINE} L {points[0]['x']},{CHART_BASELINE} Z"
        )

    return {
        "points": points,
        "path": path,
        "area_path": area_path,
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "baseline": CHART_BASELINE,
        "max_value": max_value,
    }


def _percent_delta(current, previous):
    """Percentage change from previous to current. None if previous is zero (undefined)."""
    if not previous:
        return None
    return round(((current - previous) / previous) * 100)


def _daily_series(queryset, date_field, aggregate, start, end):
    """
    One row per calendar day from start to end (inclusive), zero-filled where
    the queryset has no rows for that day — so charts never show gaps.
    """
    rows = (
        queryset.filter(**{f"{date_field}__date__gte": start, f"{date_field}__date__lte": end})
        .annotate(day=TruncDate(date_field))
        .values("day")
        .annotate(value=aggregate)
        .order_by("day")
    )
    by_day = {row["day"]: row["value"] for row in rows}

    series = []
    current = start
    while current <= end:
        series.append({"date": current, "value": by_day.get(current) or 0})
        current += timedelta(days=1)
    return series


@role_required("ADMIN")
def admin_dashboard(request):
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    window_start = today - timedelta(days=13)

    # --- KPIs ---
    total_patients = Patient.objects.count()

    todays_appointments = Appointment.objects.filter(appointment_date__date=today).count()
    yesterdays_appointments = Appointment.objects.filter(appointment_date__date=yesterday).count()

    active_visits = Visit.objects.exclude(status=Visit.Status.COMPLETED).count()

    todays_revenue = Payment.objects.filter(payment_date__date=today).aggregate(
        total=Coalesce(Sum("amount_paid"), Decimal("0"))
    )["total"]
    yesterdays_revenue = Payment.objects.filter(payment_date__date=yesterday).aggregate(
        total=Coalesce(Sum("amount_paid"), Decimal("0"))
    )["total"]

    total_billed = VisitInvoice.objects.aggregate(total=Coalesce(Sum("total_amount"), Decimal("0")))[
        "total"
    ]
    total_collected = Payment.objects.aggregate(total=Coalesce(Sum("amount_paid"), Decimal("0")))[
        "total"
    ]
    outstanding_balance = total_billed - total_collected

    total_beds = Bed.objects.count()
    occupied_beds = Bed.objects.filter(is_occupied=True).count()
    bed_occupancy_pct = round((occupied_beds / total_beds) * 100) if total_beds else 0

    low_stock_drugs = (
        Drug.objects.annotate(total_quantity=Coalesce(Sum("stock_entries__quantity"), 0))
        .filter(total_quantity__lte=0)
        .count()
    )

    total_staff = User.objects.filter(is_active=True).exclude(role=User.Role.PATIENT).count()

    # --- 14-day trends ---
    appointments_series = _daily_series(
        Appointment.objects.all(), "appointment_date", Count("id"), window_start, today
    )
    revenue_series = _daily_series(
        Payment.objects.all(),
        "payment_date",
        Coalesce(Sum("amount_paid"), Decimal("0")),
        window_start,
        today,
    )

    # --- Current operational snapshot ---
    status_labels = dict(Visit.Status.choices)
    visits_by_status = [
        {"label": status_labels[row["status"]], "count": row["count"]}
        for row in Visit.objects.values("status").annotate(count=Count("id")).order_by("status")
    ]

    visits_by_department = [
        {"label": row["department__name"] or "Unassigned", "count": row["count"]}
        for row in (
            Visit.objects.exclude(status=Visit.Status.COMPLETED)
            .values("department__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
    ]

    wards = Ward.objects.select_related("department").annotate(
        bed_count=Count("beds", distinct=True),
        occupied_count=Count("beds", filter=Q(beds__is_occupied=True), distinct=True),
    ).order_by("name")
    for ward in wards:
        ward.occupancy_pct = round((ward.occupied_count / ward.bed_count) * 100) if ward.bed_count else 0

    departments = Department.objects.annotate(
        doctor_count=Count("doctors", distinct=True),
        nurse_count=Count("nurses", distinct=True),
        active_visit_count=Count(
            "visits", filter=~Q(visits__status=Visit.Status.COMPLETED), distinct=True
        ),
    ).order_by("name")

    staff_by_role = (
        User.objects.filter(is_active=True)
        .exclude(role=User.Role.PATIENT)
        .values("role")
        .annotate(count=Count("id"))
        .order_by("role")
    )
    role_labels = dict(User.Role.choices)
    staff_by_role = [
        {"label": role_labels[row["role"]], "count": row["count"]} for row in staff_by_role
    ]

    context = {
        "total_patients": total_patients,
        "todays_appointments": todays_appointments,
        "appointments_delta": _percent_delta(todays_appointments, yesterdays_appointments),
        "active_visits": active_visits,
        "todays_revenue": todays_revenue,
        "revenue_delta": _percent_delta(todays_revenue, yesterdays_revenue),
        "outstanding_balance": outstanding_balance,
        "bed_occupancy_pct": bed_occupancy_pct,
        "occupied_beds": occupied_beds,
        "total_beds": total_beds,
        "low_stock_drugs": low_stock_drugs,
        "total_staff": total_staff,
        "appointments_chart": _build_bar_chart(appointments_series, value_key="value"),
        "revenue_chart": _build_line_chart(revenue_series),
        "status_chart": _build_bar_chart(visits_by_status, value_key="count"),
        "department_chart": _build_bar_chart(visits_by_department, value_key="count", max_bars=8),
        "wards": wards,
        "departments": departments,
        "staff_by_role": staff_by_role,
        "recent_patients": Patient.objects.order_by("-created_at")[:5],
        "recent_payments": Payment.objects.select_related("invoice__patient").order_by(
            "-payment_date"
        )[:5],
    }
    return render(request, "dashboards/admin.html", context)