from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Admission,
    Appointment,
    AuditLog,
    Bed,
    Department,
    Doctor,
    Drug,
    InvoiceItem,
    LabOrder,
    LabOrderItem,
    LabResult,
    LabTest,
    MedicalRecord,
    Nurse,
    Patient,
    Payment,
    Prescription,
    PrescriptionItem,
    QueueTicket,
    RefillRequest,
    Service,
    ServiceGate,
    Stock,
    StockTransaction,
    User,
    Visit,
    VisitInvoice,
    VitalSigns,
    Ward,
)


# =====================================================================
# Users & staff
# =====================================================================

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Extends Django's built-in UserAdmin so `role`/`phone_number` show up."""
    list_display = ("username", "get_full_name", "role", "email", "is_staff", "is_active")
    list_filter = BaseUserAdmin.list_filter + ("role",)
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Hospital info", {"fields": ("role", "phone_number")}),
    )

    @admin.display(description="Full name")
    def get_full_name(self, obj):
        return obj.get_full_name()


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("__str__", "specialization", "department")
    list_filter = ("department",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "specialization")
    autocomplete_fields = ("user",)


@admin.register(Nurse)
class NurseAdmin(admin.ModelAdmin):
    list_display = ("__str__", "department")
    list_filter = ("department",)
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


# =====================================================================
# Patients, appointments & visits
# =====================================================================

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "full_name", "patient_number", "gender", "date_of_birth", "phone", "blood_group", "user",
    )
    list_filter = ("gender", "blood_group")
    search_fields = ("full_name", "patient_number", "phone")
    date_hierarchy = "created_at"
    autocomplete_fields = ("user",)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "department", "appointment_date", "status")
    list_filter = ("status", "department")
    search_fields = ("patient__full_name", "patient__patient_number")
    date_hierarchy = "appointment_date"
    autocomplete_fields = ("patient", "doctor", "department")


class VitalSignsInline(admin.TabularInline):
    model = VitalSigns
    extra = 0


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "visit_type", "status", "visit_date")
    list_filter = ("status", "visit_type", "department")
    search_fields = ("patient__full_name", "patient__patient_number")
    date_hierarchy = "visit_date"
    autocomplete_fields = ("patient", "doctor", "department", "appointment")
    inlines = [VitalSignsInline]


@admin.register(MedicalRecord)
class MedicalRecordAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "visit", "created_at")
    search_fields = ("patient__full_name", "diagnosis")
    date_hierarchy = "created_at"
    autocomplete_fields = ("patient", "doctor", "visit")


@admin.register(VitalSigns)
class VitalSignsAdmin(admin.ModelAdmin):
    list_display = ("visit", "temperature", "pulse_rate", "blood_pressure", "recorded_by", "recorded_at")
    date_hierarchy = "recorded_at"
    autocomplete_fields = ("visit", "recorded_by")


# =====================================================================
# Pharmacy
# =====================================================================

@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "strength", "unit_price", "manufacturer")
    list_filter = ("category",)
    search_fields = ("name", "category", "manufacturer")


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 1
    autocomplete_fields = ("drug",)


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "created_at")
    search_fields = ("patient__full_name",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("patient", "doctor", "visit")
    inlines = [PrescriptionItemInline]


@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(admin.ModelAdmin):
    list_display = ("drug", "prescription", "dosage", "frequency", "duration")
    search_fields = ("drug__name", "prescription__patient__full_name")
    autocomplete_fields = ("drug", "prescription")


@admin.register(RefillRequest)
class RefillRequestAdmin(admin.ModelAdmin):
    list_display = ("patient", "prescription_item", "status", "requested_at", "reviewed_by")
    list_filter = ("status",)
    search_fields = ("patient__full_name", "prescription_item__drug__name")
    date_hierarchy = "requested_at"
    autocomplete_fields = ("patient", "prescription_item", "reviewed_by", "new_prescription_item")


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("drug", "quantity", "batch_number", "expiry_date")
    list_filter = ("expiry_date",)
    search_fields = ("drug__name", "batch_number")
    autocomplete_fields = ("drug",)


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ("drug", "type", "quantity", "reason", "date")
    list_filter = ("type",)
    search_fields = ("drug__name",)
    date_hierarchy = "date"
    autocomplete_fields = ("drug",)


# =====================================================================
# Laboratory
# =====================================================================

@admin.register(LabTest)
class LabTestAdmin(admin.ModelAdmin):
    list_display = ("name", "price")
    search_fields = ("name",)


class LabOrderItemInline(admin.TabularInline):
    model = LabOrderItem
    extra = 1
    autocomplete_fields = ("test",)


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("patient__full_name",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("patient", "doctor", "visit")
    inlines = [LabOrderItemInline]


@admin.register(LabOrderItem)
class LabOrderItemAdmin(admin.ModelAdmin):
    list_display = ("lab_order", "test")
    autocomplete_fields = ("lab_order", "test")


@admin.register(LabResult)
class LabResultAdmin(admin.ModelAdmin):
    list_display = ("lab_order", "test", "result_value", "result_date")
    search_fields = ("lab_order__patient__full_name", "test__name")
    date_hierarchy = "result_date"
    autocomplete_fields = ("lab_order", "test")


# =====================================================================
# Billing
# =====================================================================

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "service_type", "price")
    list_filter = ("service_type",)
    search_fields = ("name",)


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    autocomplete_fields = ("service",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("payment_date",)


@admin.register(VisitInvoice)
class VisitInvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "total_amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("patient__full_name",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("patient", "visit")
    inlines = [InvoiceItemInline, PaymentInline]


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ("invoice", "service", "quantity", "price")
    autocomplete_fields = ("invoice", "service")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "invoice", "amount_paid", "method", "payment_date")
    list_filter = ("method",)
    search_fields = ("receipt_number", "invoice__patient__full_name")
    date_hierarchy = "payment_date"
    autocomplete_fields = ("invoice",)


# =====================================================================
# Queueing & service gates
# =====================================================================

@admin.register(QueueTicket)
class QueueTicketAdmin(admin.ModelAdmin):
    list_display = ("queue_number", "visit", "served", "created_at")
    list_filter = ("served",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("visit",)


@admin.register(ServiceGate)
class ServiceGateAdmin(admin.ModelAdmin):
    list_display = ("visit", "service_type", "is_cleared", "cleared_at")
    list_filter = ("service_type", "is_cleared")
    autocomplete_fields = ("visit",)


# =====================================================================
# Wards, beds & admissions
# =====================================================================

@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "capacity")
    list_filter = ("department",)
    search_fields = ("name",)


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ("bed_number", "ward", "is_occupied")
    list_filter = ("ward", "is_occupied")
    search_fields = ("bed_number", "ward__name")


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ("patient", "ward", "bed", "status", "admission_date", "discharge_date")
    list_filter = ("status", "ward")
    search_fields = ("patient__full_name",)
    date_hierarchy = "admission_date"
    autocomplete_fields = ("patient", "visit", "ward", "bed")


# =====================================================================
# Audit log — visible for inspection, but never editable through admin
# =====================================================================

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "table_name", "record_id", "ip_address")
    list_filter = ("table_name",)
    search_fields = ("user__username", "action", "table_name")
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser