from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from ..models import (
    Appointment,
    EmergencyAlert,
    InvoiceItem,
    LabOrder,
    LabResult,
    MedicalRecord,
    Message,
    Notification,
    Patient,
    Payment,
    Prescription,
    PrescriptionItem,
    RefillRequest,
    User,
    Visit,
    VisitInvoice,
    VitalSigns,
)
from ..services import days_left_for_prescription_item, patient_for_user


class PatientTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Same tenant-scoped authenticate() call as the web login (see
    login_view in views.py) — TokenObtainPairSerializer.validate() calls
    authenticate() internally, which is automatically scoped to
    request.hospital via TenantManager/ModelBackend. This is the patient
    app's only login endpoint, so non-PATIENT accounts are rejected here.
    """

    def validate(self, attrs):
        data = super().validate(attrs)

        if self.user.role != User.Role.PATIENT:
            raise AuthenticationFailed("This login is for patients only.")

        patient = patient_for_user(self.user)
        data["role"] = self.user.role
        data["patient_id"] = patient.pk if patient else None
        return data


class DoctorSerializer(serializers.ModelSerializer):
    """Lightweight doctor representation — used wherever the web templates
    just show "Dr. {name}" (appointments, messages, prescriptions...)."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.username


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = [
            "id", "full_name", "gender", "date_of_birth", "phone", "address",
            "blood_group", "patient_number", "emergency_contact_name", "emergency_contact_phone",
        ]


class DepartmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class AppointmentSerializer(serializers.ModelSerializer):
    doctor = DoctorSerializer(read_only=True)
    department_name = serializers.CharField(source="department.name", default=None, read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "doctor", "department", "department_name", "appointment_date",
            "reason", "status", "consultation_type", "meeting_link",
        ]
        read_only_fields = ["status", "meeting_link"]


class TelemedicineRequestSerializer(serializers.ModelSerializer):
    """POST body for requesting a telemedicine visit — mirrors
    PatientTelemedicineForm (forms.py): doctor optional, patient/
    consultation_type are fixed by the view, never client-supplied."""

    class Meta:
        model = Appointment
        fields = ["doctor", "department", "appointment_date", "reason"]
        extra_kwargs = {"doctor": {"required": False, "allow_null": True}}

    def validate_appointment_date(self, value):
        if value < timezone.now():
            raise serializers.ValidationError("Appointment date/time cannot be in the past.")
        return value


class VitalSignsSerializer(serializers.ModelSerializer):
    class Meta:
        model = VitalSigns
        fields = ["id", "temperature", "pulse_rate", "blood_pressure", "weight", "height", "recorded_at"]


class LabResultSerializer(serializers.ModelSerializer):
    test_name = serializers.CharField(source="test.name", read_only=True)

    class Meta:
        model = LabResult
        fields = ["id", "test_name", "result_value", "normal_range", "remarks", "result_date"]


class MedicalRecordSerializer(serializers.ModelSerializer):
    doctor = DoctorSerializer(read_only=True)

    class Meta:
        model = MedicalRecord
        fields = ["id", "doctor", "diagnosis", "notes", "created_at"]


class PrescriptionItemSerializer(serializers.ModelSerializer):
    drug_name = serializers.CharField(source="drug.name", read_only=True)
    days_left = serializers.SerializerMethodField()
    has_pending_refill = serializers.SerializerMethodField()

    class Meta:
        model = PrescriptionItem
        fields = [
            "id", "drug_name", "quantity", "dosage", "frequency", "duration",
            "instructions", "dispensed", "dispensed_at", "days_left", "has_pending_refill",
        ]

    def get_days_left(self, obj):
        return days_left_for_prescription_item(obj)

    def get_has_pending_refill(self, obj):
        return getattr(obj, "has_pending_request", None) or RefillRequest.objects.filter(
            prescription_item=obj, status=RefillRequest.Status.PENDING
        ).exists()


class RefillRequestSerializer(serializers.ModelSerializer):
    drug_name = serializers.CharField(source="prescription_item.drug.name", read_only=True)
    reviewed_by = DoctorSerializer(read_only=True)

    class Meta:
        model = RefillRequest
        fields = [
            "id", "prescription_item", "drug_name", "status", "requested_at",
            "reviewed_by", "reviewed_at", "denial_reason",
        ]


class PrescriptionSerializer(serializers.ModelSerializer):
    doctor = DoctorSerializer(read_only=True)
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = ["id", "doctor", "created_at", "items"]


class LabOrderItemSerializer(serializers.Serializer):
    test_name = serializers.CharField(source="test.name")


class LabOrderSerializer(serializers.ModelSerializer):
    doctor = DoctorSerializer(read_only=True)
    items = LabOrderItemSerializer(many=True, read_only=True)
    results = LabResultSerializer(many=True, read_only=True)

    class Meta:
        model = LabOrder
        fields = ["id", "doctor", "status", "created_at", "items", "results"]


class VisitSerializer(serializers.ModelSerializer):
    doctor = DoctorSerializer(read_only=True)
    department_name = serializers.CharField(source="department.name", default=None, read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id", "doctor", "department_name", "visit_type", "status",
            "visit_date", "symptoms", "diagnosis_summary",
        ]


class InvoiceItemSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = InvoiceItem
        fields = ["id", "service_name", "quantity", "price", "subtotal"]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "receipt_number", "amount_paid", "method", "reference", "payment_date"]


class VisitInvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = VisitInvoice
        fields = [
            "id", "total_amount", "status", "created_at", "items", "payments",
            "amount_paid", "balance_due",
        ]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "description", "is_read", "created_at"]


class MessageSerializer(serializers.ModelSerializer):
    sender_is_me = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "body", "created_at", "is_read", "sender_is_me"]

    def get_sender_is_me(self, obj):
        request = self.context.get("request")
        return bool(request and obj.sender_id == request.user.id)


class MessageComposeSerializer(serializers.Serializer):
    """POST body for starting a new conversation — `doctor` is validated
    against the same "has actually treated this patient" queryset the web
    view (patient_messages) builds, passed in via context."""

    doctor = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    body = serializers.CharField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        doctor_queryset = self.context.get("doctor_queryset")
        if doctor_queryset is not None:
            self.fields["doctor"].queryset = doctor_queryset


class MessageReplySerializer(serializers.Serializer):
    body = serializers.CharField()


class EmergencyAlertSerializer(serializers.Serializer):
    severity = serializers.ChoiceField(choices=EmergencyAlert.Severity.choices)
    details = serializers.CharField(required=False, allow_blank=True, default="")
    share_location = serializers.BooleanField(required=False, default=False)
    latitude = serializers.FloatField(required=False, allow_null=True, default=None)
    longitude = serializers.FloatField(required=False, allow_null=True, default=None)
