from django import forms
from django.utils import timezone

from .models import Appointment, LabTest, MedicalRecord, Patient, PrescriptionItem, VitalSigns


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
        fields = ["drug", "dosage", "frequency", "duration", "instructions"]
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 2}),
        }


class LabOrderItemForm(forms.Form):
    test = forms.ModelChoiceField(queryset=LabTest.objects.all())
