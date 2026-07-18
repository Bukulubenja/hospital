from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from ..models import (
    Appointment,
    Department,
    EmergencyAlert,
    LabOrder,
    LabResult,
    MedicalRecord,
    Message,
    Notification,
    Prescription,
    PrescriptionItem,
    RefillRequest,
    User,
    Visit,
    VisitInvoice,
)
from ..services import create_notification, patient_for_user, queue_snapshot_for_patient
from .permissions import IsPatientRole
from .serializers import (
    AppointmentSerializer,
    DepartmentSerializer,
    DoctorSerializer,
    EmergencyAlertSerializer,
    LabOrderSerializer,
    LabResultSerializer,
    MedicalRecordSerializer,
    MessageComposeSerializer,
    MessageReplySerializer,
    MessageSerializer,
    NotificationSerializer,
    PatientSerializer,
    PatientTokenObtainPairSerializer,
    PrescriptionItemSerializer,
    PrescriptionSerializer,
    RefillRequestSerializer,
    TelemedicineRequestSerializer,
    VisitInvoiceSerializer,
    VisitSerializer,
)


class PatientTokenObtainPairView(TokenObtainPairView):
    serializer_class = PatientTokenObtainPairSerializer


def patient_api_view(methods):
    """DRF equivalent of hospital.decorators.role_required("PATIENT") — every
    endpoint below is patient-app-only."""

    def decorator(view_func):
        view_func = permission_classes([IsAuthenticated, IsPatientRole])(view_func)
        view_func = api_view(methods)(view_func)
        return view_func

    return decorator


class _PatientNotLinked(Exception):
    pass


def _require_patient(request):
    patient = patient_for_user(request.user)
    if patient is None:
        raise _PatientNotLinked()
    return patient


def _not_linked_response():
    return Response(
        {"detail": "Your account isn't linked to a patient record yet."},
        status=status.HTTP_404_NOT_FOUND,
    )


@patient_api_view(["GET"])
def dashboard(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return Response({"patient": None})

    now = timezone.now()
    last_visit = patient.visits.order_by("-visit_date").first()
    invoices = list(VisitInvoice.objects.filter(patient=patient))
    total_paid = sum((invoice.amount_paid for invoice in invoices), 0)
    total_due = sum((invoice.balance_due for invoice in invoices), 0)

    active_prescription_items = list(
        PrescriptionItem.objects.filter(prescription__patient=patient, dispensed=True)
        .select_related("drug", "prescription")
        .order_by("-prescription__created_at")[:10]
    )

    notifications_qs = Notification.objects.filter(user=request.user).order_by("-created_at")
    recent_messages = list(
        Message.objects.filter(patient=patient)
        .select_related("doctor", "sender")
        .order_by("-created_at")[:5]
    )

    queue_snapshot = queue_snapshot_for_patient(patient)
    if queue_snapshot:
        queue_snapshot["estimated_time"] = queue_snapshot["estimated_time"].isoformat()

    data = {
        "patient": PatientSerializer(patient).data,
        "latest_visit_summary": last_visit.diagnosis_summary if last_visit else "",
        "upcoming_appointments": AppointmentSerializer(
            patient.appointments.select_related("doctor", "department")
            .filter(appointment_date__gte=now, status=Appointment.Status.SCHEDULED)
            .order_by("appointment_date"),
            many=True,
        ).data,
        "recent_lab_results": LabResultSerializer(
            LabResult.objects.filter(lab_order__patient=patient)
            .select_related("test", "lab_order")
            .order_by("-result_date")[:5],
            many=True,
        ).data,
        "medical_history": MedicalRecordSerializer(
            MedicalRecord.objects.filter(patient=patient)
            .select_related("doctor", "visit")
            .order_by("-created_at")[:10],
            many=True,
        ).data,
        "active_prescription_items": PrescriptionItemSerializer(active_prescription_items, many=True).data,
        "recent_refill_requests": RefillRequestSerializer(
            patient.refill_requests.select_related("prescription_item__drug", "reviewed_by")[:5], many=True
        ).data,
        "total_paid": total_paid,
        "total_due": total_due,
        "recent_invoices": VisitInvoiceSerializer(
            VisitInvoice.objects.filter(patient=patient).order_by("-created_at")[:5], many=True
        ).data,
        "recent_notifications": NotificationSerializer(notifications_qs[:5], many=True).data,
        "unread_notification_count": notifications_qs.filter(is_read=False).count(),
        "recent_messages": MessageSerializer(recent_messages, many=True, context={"request": request}).data,
        "queue_snapshot": queue_snapshot,
    }
    return Response(data)


@patient_api_view(["POST"])
def appointment_cancel(request, pk):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    appointment = get_object_or_404(Appointment, pk=pk, patient=patient)
    if appointment.status != Appointment.Status.SCHEDULED:
        return Response(
            {"detail": "Only scheduled appointments can be cancelled."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    appointment.status = Appointment.Status.CANCELLED
    appointment.save(update_fields=["status"])
    return Response(AppointmentSerializer(appointment).data)


@patient_api_view(["GET"])
def notifications_list(request):
    notifications = Notification.objects.filter(user=request.user).order_by("-created_at")
    return Response(NotificationSerializer(notifications, many=True).data)


@patient_api_view(["POST"])
def notifications_mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({"ok": True})


@patient_api_view(["POST"])
def emergency_alert_create(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    serializer = EmergencyAlertSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    share_location = data["share_location"]
    EmergencyAlert.objects.create(
        patient=patient,
        severity=data["severity"],
        details=data["details"].strip(),
        latitude=data["latitude"] if share_location else None,
        longitude=data["longitude"] if share_location else None,
    )
    return Response({"ok": True})


@patient_api_view(["POST"])
def change_password(request):
    form = PasswordChangeForm(user=request.user, data=request.data)
    if not form.is_valid():
        return Response({"errors": form.errors}, status=status.HTTP_400_BAD_REQUEST)

    form.save()
    return Response({"ok": True})


@patient_api_view(["GET", "POST"])
def messages_list(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    available_doctors = (
        User.objects.filter(role=User.Role.DOCTOR, visits_as_doctor__patient=patient)
        .distinct()
        .order_by("first_name", "last_name")
    )

    if request.method == "POST":
        serializer = MessageComposeSerializer(
            data=request.data, context={"doctor_queryset": available_doctors}
        )
        serializer.is_valid(raise_exception=True)
        doctor = serializer.validated_data["doctor"]
        body = serializer.validated_data["body"]

        message = Message.objects.create(patient=patient, doctor=doctor, sender=request.user, body=body)
        create_notification(doctor, f"New message from {patient.full_name}", body[:200])
        return Response(MessageSerializer(message, context={"request": request}).data, status=201)

    conversations = []
    for doctor in available_doctors:
        thread = Message.objects.filter(patient=patient, doctor=doctor).order_by("-created_at")
        latest = thread.first()
        unread = thread.filter(is_read=False).exclude(sender=request.user).count()
        conversations.append(
            {
                "doctor": DoctorSerializer(doctor).data,
                "latest": MessageSerializer(latest, context={"request": request}).data if latest else None,
                "unread": unread,
            }
        )
    return Response(conversations)


@patient_api_view(["GET", "POST"])
def message_thread(request, doctor_pk):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    doctor = get_object_or_404(User, pk=doctor_pk, role=User.Role.DOCTOR)
    if not Visit.objects.filter(doctor=doctor, patient=patient).exists():
        return Response(
            {"detail": "You can only message a doctor who has treated you."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == "POST":
        serializer = MessageReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = serializer.validated_data["body"]

        message = Message.objects.create(patient=patient, doctor=doctor, sender=request.user, body=body)
        create_notification(doctor, f"New message from {patient.full_name}", body[:200])
        return Response(MessageSerializer(message, context={"request": request}).data, status=201)

    thread = Message.objects.filter(patient=patient, doctor=doctor).order_by("created_at")
    thread.exclude(sender=request.user).filter(is_read=False).update(is_read=True)
    return Response(MessageSerializer(thread, many=True, context={"request": request}).data)


@patient_api_view(["GET"])
def refills_list(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

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
    refill_requests = patient.refill_requests.select_related("prescription_item__drug", "reviewed_by")

    return Response(
        {
            "eligible_items": PrescriptionItemSerializer(eligible_items, many=True).data,
            "refill_requests": RefillRequestSerializer(refill_requests, many=True).data,
        }
    )


@patient_api_view(["POST"])
def request_refill(request, item_pk):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    item = get_object_or_404(PrescriptionItem, pk=item_pk, prescription__patient=patient, dispensed=True)
    if RefillRequest.objects.filter(prescription_item=item, status=RefillRequest.Status.PENDING).exists():
        return Response(
            {"detail": f"You already have a pending refill request for {item.drug.name}."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    refill_request = RefillRequest.objects.create(patient=patient, prescription_item=item)
    return Response(RefillRequestSerializer(refill_request).data, status=201)


@patient_api_view(["GET", "POST"])
def telemedicine(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    if request.method == "POST":
        serializer = TelemedicineRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = serializer.save(
            patient=patient, consultation_type=Appointment.ConsultationType.TELEMEDICINE
        )
        return Response(AppointmentSerializer(appointment).data, status=201)

    upcoming = (
        patient.appointments.select_related("doctor", "department")
        .filter(
            consultation_type=Appointment.ConsultationType.TELEMEDICINE,
            status=Appointment.Status.SCHEDULED,
        )
        .order_by("appointment_date")
    )
    return Response(AppointmentSerializer(upcoming, many=True).data)


@patient_api_view(["GET"])
def telemedicine_history(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    past_appointments = (
        patient.appointments.select_related("doctor", "department")
        .filter(consultation_type=Appointment.ConsultationType.TELEMEDICINE)
        .exclude(status=Appointment.Status.SCHEDULED)
        .order_by("-appointment_date")
    )
    return Response(AppointmentSerializer(past_appointments, many=True).data)


@patient_api_view(["GET"])
def records(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    return Response(
        {
            "visits": VisitSerializer(
                patient.visits.select_related("doctor", "department").order_by("-visit_date"), many=True
            ).data,
            "medical_records": MedicalRecordSerializer(
                MedicalRecord.objects.filter(patient=patient)
                .select_related("doctor", "visit")
                .order_by("-created_at"),
                many=True,
            ).data,
            "prescriptions": PrescriptionSerializer(
                Prescription.objects.filter(patient=patient)
                .prefetch_related("items__drug")
                .order_by("-created_at"),
                many=True,
            ).data,
            "lab_orders": LabOrderSerializer(
                LabOrder.objects.filter(patient=patient)
                .prefetch_related("items__test", "results__test")
                .order_by("-created_at"),
                many=True,
            ).data,
            "generated_at": timezone.now().isoformat(),
        }
    )


@patient_api_view(["GET"])
def lab_results_list(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    results = (
        LabResult.objects.filter(lab_order__patient=patient)
        .select_related("test", "lab_order")
        .order_by("-result_date")
    )
    return Response(LabResultSerializer(results, many=True).data)


@patient_api_view(["GET"])
def invoices_list(request):
    try:
        patient = _require_patient(request)
    except _PatientNotLinked:
        return _not_linked_response()

    invoices = (
        VisitInvoice.objects.filter(patient=patient)
        .prefetch_related("items__service", "payments")
        .order_by("-created_at")
    )
    return Response(VisitInvoiceSerializer(invoices, many=True).data)


@patient_api_view(["GET"])
def departments_list(request):
    """Small reference-data endpoint the mobile telemedicine-request screen
    needs for its department picker (mirrors the "departments" context key
    on the web dashboard)."""
    return Response(DepartmentSerializer(Department.objects.all(), many=True).data)
