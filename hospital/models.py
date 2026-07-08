from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models


# =====================================================================
# Shared abstract base
# =====================================================================

class TimeStampedModel(models.Model):
    """Adds created/updated timestamps to any model that inherits it."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# =====================================================================
# Users & Staff
# =====================================================================

class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        DOCTOR = "DOCTOR", "Doctor"
        NURSE = "NURSE", "Nurse"
        RECEPTIONIST = "RECEPTIONIST", "Receptionist"
        LAB = "LAB", "Lab Technician"
        PHARMACIST = "PHARMACIST", "Pharmacist"
        CASHIER = "CASHIER", "Cashier"
        PATIENT = "PATIENT", "Patient"
        STOCK_MANAGER = "STOCK_MANAGER", "Stock Manager"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["role"])]

    def __str__(self):
        return self.get_full_name() or self.username


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Doctor(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="doctor_profile"
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name="doctors"
    )
    specialization = models.CharField(max_length=200)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Nurse(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="nurse_profile"
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name="nurses"
    )

    def __str__(self):
        return self.user.get_full_name() or self.user.username


# =====================================================================
# Patients, Appointments & Visits
# =====================================================================

class Patient(models.Model):

    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    full_name = models.CharField(max_length=200)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    date_of_birth = models.DateField()
    phone = models.CharField(max_length=20, db_index=True)
    address = models.TextField(blank=True)
    blood_group = models.CharField(max_length=5, blank=True)
    patient_number = models.CharField(max_length=20, unique=True)

    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)

    # The portal login for this patient, if one has been created. Nullable —
    # most Patient rows (walk-ins registered by Reception) never get a login
    # at all. Linked by an ADMIN in Django admin after creating the User,
    # not auto-created by a signal, since the Patient row already exists.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_profile",
        limit_choices_to={"role": "PATIENT"},
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.patient_number})"


class Appointment(models.Model):

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"
        NO_SHOW = "NO_SHOW", "No Show"

    class ConsultationType(models.TextChoices):
        IN_PERSON = "IN_PERSON", "In Person"
        TELEMEDICINE = "TELEMEDICINE", "Telemedicine"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="appointments_as_doctor",
        limit_choices_to={"role": User.Role.DOCTOR},
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name="appointments"
    )

    appointment_date = models.DateTimeField(db_index=True)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    consultation_type = models.CharField(
        max_length=20, choices=ConsultationType.choices, default=ConsultationType.IN_PERSON, blank=True
    )
    # External video-call link for TELEMEDICINE appointments. No in-app
    # video/chat is built — this just carries a link to a third-party tool.
    meeting_link = models.URLField(blank=True)

    class Meta:
        ordering = ["-appointment_date"]

    def __str__(self):
        return f"{self.patient.full_name} - {self.appointment_date:%Y-%m-%d %H:%M}"


class Visit(models.Model):

    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Registered"
        WAITING_DOCTOR = "WAITING_DOCTOR", "Waiting for Doctor"
        IN_CONSULTATION = "IN_CONSULTATION", "In Consultation"
        WAITING_LAB = "WAITING_LAB", "Waiting for Lab"
        WAITING_PHARMACY = "WAITING_PHARMACY", "Waiting for Pharmacy"
        COMPLETED = "COMPLETED", "Completed"

    class VisitType(models.TextChoices):
        OPD = "OPD", "Outpatient"
        EMERGENCY = "EMERGENCY", "Emergency"
        INPATIENT = "INPATIENT", "Inpatient"

    appointment = models.OneToOneField(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True, related_name="visit"
    )
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="visits")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="visits_as_doctor",
        limit_choices_to={"role": User.Role.DOCTOR},
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name="visits"
    )

    visit_type = models.CharField(max_length=20, choices=VisitType.choices)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.REGISTERED, db_index=True
    )
    visit_date = models.DateTimeField(auto_now_add=True)

    symptoms = models.TextField(blank=True)
    diagnosis_summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-visit_date"]

    def __str__(self):
        return f"{self.patient.full_name} - {self.visit_date:%Y-%m-%d %H:%M}"


class MedicalRecord(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="medical_records")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="medical_records")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="medical_records_written",
    )

    diagnosis = models.TextField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Medical Record for {self.patient.full_name} - {self.visit.visit_date:%Y-%m-%d}"


class VitalSigns(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="vital_signs")

    temperature = models.DecimalField(max_digits=5, decimal_places=2)
    pulse_rate = models.PositiveIntegerField()
    blood_pressure = models.CharField(max_length=20)
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    height = models.DecimalField(max_digits=5, decimal_places=2)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="vitals_recorded"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Vital signs"
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"Vital Signs for {self.visit.patient.full_name} - {self.visit.visit_date:%Y-%m-%d}"


# =====================================================================
# Pharmacy
# =====================================================================

class Drug(models.Model):
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    strength = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    manufacturer = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.strength})"


class Prescription(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="prescriptions")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="prescriptions_written"
    )
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="prescriptions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Prescription for {self.patient.full_name} - {self.created_at:%Y-%m-%d}"


class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, related_name="prescription_items")

    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    dosage = models.CharField(max_length=100)
    frequency = models.CharField(max_length=100)
    duration = models.CharField(max_length=100)
    instructions = models.TextField(blank=True)

    dispensed = models.BooleanField(default=False)
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescription_items_dispensed",
    )

    def __str__(self):
        return f"{self.drug.name} for {self.prescription.patient.full_name}"


class RefillRequest(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        DENIED = "DENIED", "Denied"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="refill_requests")
    prescription_item = models.ForeignKey(
        PrescriptionItem, on_delete=models.CASCADE, related_name="refill_requests"
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refill_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    denial_reason = models.CharField(max_length=300, blank=True)

    # The freshly-created PrescriptionItem (on its own new Visit) that
    # fulfills this request once approved — set by approve_refill_request()
    # in services.py so the approval can be traced back to what it produced.
    new_prescription_item = models.OneToOneField(
        PrescriptionItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refill_source_request",
    )

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Refill request for {self.prescription_item.drug.name} - {self.get_status_display()}"


class Stock(models.Model):
    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name="stock_entries")
    quantity = models.PositiveIntegerField()
    expiry_date = models.DateField(db_index=True)
    batch_number = models.CharField(max_length=100)

    class Meta:
        ordering = ["expiry_date"]
        constraints = [
            models.UniqueConstraint(fields=["drug", "batch_number"], name="unique_drug_batch")
        ]

    def __str__(self):
        return f"{self.drug.name} - {self.quantity} units (Batch: {self.batch_number})"


class StockTransaction(models.Model):

    class TransactionType(models.TextChoices):
        IN = "IN", "Stock In"
        OUT = "OUT", "Stock Out"

    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=10, choices=TransactionType.choices)
    quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=200, blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_type_display()} - {self.drug.name} - {self.quantity}"


# =====================================================================
# Laboratory
# =====================================================================

class LabTest(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LabOrder(models.Model):

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="lab_orders")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="lab_orders")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="lab_orders_requested"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Lab Order for {self.patient.full_name} - {self.get_status_display()}"


class LabOrderItem(models.Model):
    lab_order = models.ForeignKey(LabOrder, on_delete=models.CASCADE, related_name="items")
    test = models.ForeignKey(LabTest, on_delete=models.PROTECT, related_name="order_items")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lab_order", "test"], name="unique_test_per_order")
        ]

    def __str__(self):
        return f"{self.test.name} for {self.lab_order.patient.full_name}"


class LabResult(models.Model):
    lab_order = models.ForeignKey(LabOrder, on_delete=models.CASCADE, related_name="results")
    test = models.ForeignKey(LabTest, on_delete=models.PROTECT, related_name="results")

    result_value = models.CharField(max_length=200)
    normal_range = models.CharField(max_length=200, blank=True)
    remarks = models.TextField(blank=True)
    result_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-result_date"]

    def __str__(self):
        return f"Lab Result for {self.lab_order.patient.full_name} - {self.test.name}"


# =====================================================================
# Billing
# =====================================================================

class Service(models.Model):

    class ServiceType(models.TextChoices):
        APPOINTMENT = "APPOINTMENT", "Appointment Fee"
        LAB = "LAB", "Lab Fee"
        PHARMACY = "PHARMACY", "Pharmacy Fee"

    name = models.CharField(max_length=100)
    service_type = models.CharField(max_length=30, choices=ServiceType.choices)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class VisitInvoice(models.Model):

    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="invoices")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="invoices")

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invoice #{self.id} - {self.patient.full_name}"

    @property
    def amount_paid(self):
        return sum(p.amount_paid for p in self.payments.all())

    @property
    def balance_due(self):
        return self.total_amount - self.amount_paid


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(VisitInvoice, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="invoice_items")

    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    def __str__(self):
        return f"{self.service.name} - {self.quantity} x {self.price}"

    @property
    def subtotal(self):
        return self.quantity * self.price


class Payment(models.Model):

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        MOBILE_MONEY = "MOBILE_MONEY", "Mobile Money"
        INSURANCE = "INSURANCE", "Insurance"

    receipt_number = models.CharField(max_length=30, unique=True)
    invoice = models.ForeignKey(VisitInvoice, on_delete=models.CASCADE, related_name="payments")
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    reference = models.CharField(max_length=200, blank=True)
    payment_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date"]

    def __str__(self):
        return f"Payment of {self.amount_paid} for Invoice #{self.invoice.id}"


# =====================================================================
# Queueing & Service Gates
# =====================================================================

class QueueTicket(models.Model):
    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name="queue_ticket")

    queue_number = models.PositiveIntegerField()
    served = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Queue Ticket {self.queue_number} for {self.visit.patient.full_name}"


class ServiceGate(models.Model):

    class GateType(models.TextChoices):
        CONSULTATION = "CONSULTATION", "Consultation"
        LAB = "LAB", "Laboratory"
        PHARMACY = "PHARMACY", "Pharmacy"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="service_gates")
    service_type = models.CharField(max_length=30, choices=GateType.choices)
    is_cleared = models.BooleanField(default=False)
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["visit", "service_type"], name="unique_gate_per_visit")
        ]

    def __str__(self):
        status = "Cleared" if self.is_cleared else "Pending"
        return f"{self.get_service_type_display()} Gate for {self.visit.patient.full_name} - {status}"


# =====================================================================
# Wards, Beds & Admissions
# =====================================================================

class Ward(models.Model):
    name = models.CharField(max_length=100)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, related_name="wards"
    )
    capacity = models.PositiveIntegerField()

    def __str__(self):
        return self.name


class Bed(models.Model):
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds")
    bed_number = models.CharField(max_length=20)
    is_occupied = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ward", "bed_number"], name="unique_bed_per_ward")
        ]

    def __str__(self):
        return f"Bed {self.bed_number} in {self.ward.name}"


class Admission(models.Model):

    class Status(models.TextChoices):
        ADMITTED = "ADMITTED", "Admitted"
        DISCHARGED = "DISCHARGED", "Discharged"
        TRANSFERRED = "TRANSFERRED", "Transferred"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="admissions")
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="admissions")

    ward = models.ForeignKey(Ward, on_delete=models.SET_NULL, null=True, related_name="admissions")
    bed = models.ForeignKey(Bed, on_delete=models.SET_NULL, null=True, related_name="admissions")

    admission_date = models.DateTimeField(auto_now_add=True)
    discharge_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ADMITTED)

    class Meta:
        ordering = ["-admission_date"]

    def __str__(self):
        return f"Admission of {self.patient.full_name} - {self.get_status_display()}"


# =====================================================================
# Audit
# =====================================================================

class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="audit_logs"
    )

    action = models.CharField(max_length=200)
    table_name = models.CharField(max_length=100, db_index=True)
    record_id = models.PositiveIntegerField()

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        username = self.user.username if self.user else "Unknown User"
        return f"{username} - {self.action} on {self.table_name} (ID: {self.record_id})"