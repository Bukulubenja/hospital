from django import forms
from django.utils import timezone

from .models import (
    Appointment,
    LabResult,
    LabTest,
    MedicalRecord,
    Patient,
    Payment,
    PrescriptionItem,
    Service,
    Stock,
    VitalSigns,
)


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "full_name",
            "gender",
            "date_of_birth",
            "phone",
            "address",
            "blood_group",
            "emergency_contact_name",
            "emergency_contact_phone",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_date_of_birth(self):
        dob = self.cleaned_data["date_of_birth"]
        if dob > timezone.localdate():
            raise forms.ValidationError("Date of birth cannot be in the future.")
        return dob


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ["patient", "doctor", "department", "appointment_date", "reason"]
        widgets = {
            "appointment_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "reason": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.order_by("full_name")

    def clean_appointment_date(self):
        appointment_date = self.cleaned_data["appointment_date"]
        if appointment_date < timezone.now():
            raise forms.ValidationError("Appointment date/time cannot be in the past.")
        return appointment_date


class VitalSignsForm(forms.ModelForm):
    class Meta:
        model = VitalSigns
        fields = ["temperature", "pulse_rate", "blood_pressure", "weight", "height"]


class MedicalRecordForm(forms.ModelForm):
    class Meta:
        model = MedicalRecord
        fields = ["diagnosis", "notes"]
        widgets = {
            "diagnosis": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class PrescriptionItemForm(forms.ModelForm):
    class Meta:
        model = PrescriptionItem
        fields = ["drug", "quantity", "dosage", "frequency", "duration", "instructions"]
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 2}),
        }


class LabOrderItemForm(forms.Form):
    test = forms.ModelChoiceField(queryset=LabTest.objects.all())


class LabResultForm(forms.ModelForm):
    class Meta:
        model = LabResult
        fields = ["result_value", "normal_range", "remarks"]
        widgets = {
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }


class InvoiceItemForm(forms.Form):
    service = forms.ModelChoiceField(queryset=Service.objects.all())
    quantity = forms.IntegerField(min_value=1, initial=1)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount_paid", "method", "reference"]

    def __init__(self, *args, invoice=None, **kwargs):
        self.invoice = invoice
        super().__init__(*args, **kwargs)

    def clean_amount_paid(self):
        amount = self.cleaned_data["amount_paid"]
        if amount <= 0:
            raise forms.ValidationError("Amount paid must be greater than zero.")
        if self.invoice is not None and amount > self.invoice.balance_due:
            raise forms.ValidationError(
                f"Amount exceeds the outstanding balance of {self.invoice.balance_due}."
            )
        return amount


class ReceiveStockForm(forms.Form):
    batch_number = forms.CharField(max_length=100)
    quantity = forms.IntegerField(min_value=1)
    expiry_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def clean_expiry_date(self):
        expiry_date = self.cleaned_data["expiry_date"]
        if expiry_date <= timezone.localdate():
            raise forms.ValidationError("Expiry date must be in the future.")
        return expiry_date


class StockAdjustmentForm(forms.Form):
    batch = forms.ModelChoiceField(queryset=Stock.objects.none())
    quantity = forms.IntegerField(min_value=1)
    reason = forms.CharField(max_length=200)

    def __init__(self, *args, drug=None, **kwargs):
        super().__init__(*args, **kwargs)
        if drug is not None:
            self.fields["batch"].queryset = drug.stock_entries.all()
