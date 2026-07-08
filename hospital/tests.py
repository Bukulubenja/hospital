from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Appointment,
    Department,
    Drug,
    LabOrderItem,
    LabTest,
    MedicalRecord,
    Patient,
    PrescriptionItem,
    QueueTicket,
    User,
    Visit,
    VitalSigns,
)


class ReceptionWorkflowTests(TestCase):
    def setUp(self):
        self.receptionist = User.objects.create_user(
            username="reception1", password="pass1234", role=User.Role.RECEPTIONIST
        )
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.department = Department.objects.create(name="General Medicine")
        self.client.login(username="reception1", password="pass1234")

    def test_non_receptionist_denied(self):
        User.objects.create_user(username="nurse1", password="pass1234", role=User.Role.NURSE)
        self.client.logout()
        self.client.login(username="nurse1", password="pass1234")

        response = self.client.get(reverse("reception_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_redirects_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("reception_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_patient_registration_generates_patient_number(self):
        response = self.client.post(reverse("patient_create"), {
            "full_name": "Jane Doe",
            "gender": "F",
            "date_of_birth": "1990-05-01",
            "phone": "0700000000",
            "address": "",
            "blood_group": "O+",
            "emergency_contact_name": "",
            "emergency_contact_phone": "",
        })

        patient = Patient.objects.get(full_name="Jane Doe")
        self.assertTrue(patient.patient_number.startswith("P-"))
        self.assertRedirects(response, f"{reverse('appointment_create')}?patient={patient.pk}")

    def test_patient_registration_rejects_future_date_of_birth(self):
        future_dob = (timezone.localdate() + timedelta(days=1)).isoformat()

        response = self.client.post(reverse("patient_create"), {
            "full_name": "Future Person",
            "gender": "M",
            "date_of_birth": future_dob,
            "phone": "0700000001",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Patient.objects.filter(full_name="Future Person").exists())

    def test_book_appointment_and_checkin_issues_queue_ticket(self):
        patient = Patient.objects.create(
            full_name="John Smith", gender="M", date_of_birth="1985-01-01",
            phone="0711111111", patient_number="P-000001",
        )
        appointment_date = timezone.now() + timedelta(hours=1)

        response = self.client.post(reverse("appointment_create"), {
            "patient": patient.pk,
            "doctor": self.doctor.pk,
            "department": self.department.pk,
            "appointment_date": appointment_date.strftime("%Y-%m-%dT%H:%M"),
            "reason": "Check-up",
        })

        appointment = Appointment.objects.get(patient=patient)
        self.assertRedirects(response, reverse("appointment_list"))
        self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)

        checkin_response = self.client.post(reverse("appointment_checkin", args=[appointment.pk]))
        self.assertRedirects(checkin_response, reverse("reception_dashboard"))

        visit = Visit.objects.get(appointment=appointment)
        self.assertEqual(visit.status, Visit.Status.WAITING_DOCTOR)
        ticket = QueueTicket.objects.get(visit=visit)
        self.assertEqual(ticket.queue_number, 1)

        # A second check-in attempt must not create a duplicate visit/ticket.
        self.client.post(reverse("appointment_checkin", args=[appointment.pk]))
        self.assertEqual(Visit.objects.filter(appointment=appointment).count(), 1)
        self.assertEqual(QueueTicket.objects.filter(visit__appointment=appointment).count(), 1)

    def test_appointment_booking_rejects_past_datetime(self):
        patient = Patient.objects.create(
            full_name="Past Timer", gender="M", date_of_birth="1985-01-01",
            phone="0711111112", patient_number="P-000002",
        )
        past_date = timezone.now() - timedelta(hours=1)

        response = self.client.post(reverse("appointment_create"), {
            "patient": patient.pk,
            "doctor": self.doctor.pk,
            "department": self.department.pk,
            "appointment_date": past_date.strftime("%Y-%m-%dT%H:%M"),
            "reason": "Check-up",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Appointment.objects.filter(patient=patient).exists())

    def test_queue_numbers_increment_across_checkins(self):
        patient1 = Patient.objects.create(
            full_name="A One", gender="M", date_of_birth="1980-01-01",
            phone="1", patient_number="P-1",
        )
        patient2 = Patient.objects.create(
            full_name="B Two", gender="F", date_of_birth="1981-01-01",
            phone="2", patient_number="P-2",
        )
        appt1 = Appointment.objects.create(
            patient=patient1, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now(),
        )
        appt2 = Appointment.objects.create(
            patient=patient2, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now(),
        )

        self.client.post(reverse("appointment_checkin", args=[appt1.pk]))
        self.client.post(reverse("appointment_checkin", args=[appt2.pk]))

        queue_numbers = list(
            QueueTicket.objects.order_by("queue_number").values_list("queue_number", flat=True)
        )
        self.assertEqual(queue_numbers, [1, 2])

    def test_checkin_rejects_non_scheduled_appointment(self):
        patient = Patient.objects.create(
            full_name="Cancelled Case", gender="F", date_of_birth="1985-01-01",
            phone="0711111113", patient_number="P-000003",
        )
        appointment = Appointment.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now(), status=Appointment.Status.CANCELLED,
        )

        self.client.post(reverse("appointment_checkin", args=[appointment.pk]))

        self.assertFalse(Visit.objects.filter(appointment=appointment).exists())


class DoctorWorkflowTests(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.other_doctor = User.objects.create_user(
            username="doc2", password="pass1234", role=User.Role.DOCTOR
        )
        self.department = Department.objects.create(name="General Medicine")
        self.patient = Patient.objects.create(
            full_name="Sam Waiting", gender="M", date_of_birth="1990-01-01",
            phone="0700000000", patient_number="P-100001",
        )
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_DOCTOR,
        )
        self.ticket = QueueTicket.objects.create(visit=self.visit, queue_number=1)
        self.drug = Drug.objects.create(name="Amoxicillin", category="Antibiotic", strength="500mg", unit_price=10)
        self.lab_test = LabTest.objects.create(name="Full Blood Count", price=15)
        self.client.login(username="doc1", password="pass1234")

    def test_other_doctor_cannot_access_visit(self):
        self.client.logout()
        self.client.login(username="doc2", password="pass1234")

        response = self.client.get(reverse("visit_detail", args=[self.visit.pk]))

        self.assertEqual(response.status_code, 403)

    def test_start_consultation_marks_queue_served(self):
        response = self.client.post(reverse("visit_start", args=[self.visit.pk]))

        self.assertRedirects(response, reverse("visit_detail", args=[self.visit.pk]))
        self.visit.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.IN_CONSULTATION)
        self.assertTrue(self.ticket.served)

    def test_cannot_record_vitals_before_starting_consultation(self):
        self.client.post(reverse("visit_record_vitals", args=[self.visit.pk]), {
            "temperature": "37.0", "pulse_rate": "70",
            "blood_pressure": "120/80", "weight": "70", "height": "170",
        })

        self.assertEqual(VitalSigns.objects.filter(visit=self.visit).count(), 0)

    def test_full_consultation_flow_routes_to_waiting_lab(self):
        self.client.post(reverse("visit_start", args=[self.visit.pk]))

        self.client.post(reverse("visit_record_vitals", args=[self.visit.pk]), {
            "temperature": "37.5", "pulse_rate": "72",
            "blood_pressure": "118/76", "weight": "68", "height": "172",
        })
        self.assertEqual(VitalSigns.objects.filter(visit=self.visit).count(), 1)

        self.client.post(reverse("visit_record_diagnosis", args=[self.visit.pk]), {
            "diagnosis": "Suspected infection", "notes": "Follow up in a week",
        })
        self.assertEqual(MedicalRecord.objects.filter(visit=self.visit).count(), 1)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.diagnosis_summary, "Suspected infection")

        self.client.post(reverse("visit_add_prescription_item", args=[self.visit.pk]), {
            "drug": self.drug.pk, "dosage": "1 tablet", "frequency": "3x daily",
            "duration": "5 days", "instructions": "After meals",
        })
        self.assertEqual(PrescriptionItem.objects.filter(prescription__visit=self.visit).count(), 1)

        self.client.post(reverse("visit_add_lab_test", args=[self.visit.pk]), {
            "test": self.lab_test.pk,
        })
        self.assertEqual(LabOrderItem.objects.filter(lab_order__visit=self.visit).count(), 1)

        # Ordering the same test again must not create a duplicate.
        self.client.post(reverse("visit_add_lab_test", args=[self.visit.pk]), {
            "test": self.lab_test.pk,
        })
        self.assertEqual(LabOrderItem.objects.filter(lab_order__visit=self.visit).count(), 1)

        response = self.client.post(reverse("visit_complete", args=[self.visit.pk]))

        self.assertRedirects(response, reverse("doctor_dashboard"))
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.WAITING_LAB)

    def test_complete_without_orders_marks_visit_completed(self):
        self.client.post(reverse("visit_start", args=[self.visit.pk]))

        self.client.post(reverse("visit_complete", args=[self.visit.pk]))

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.COMPLETED)

    def test_prescription_only_routes_to_waiting_pharmacy(self):
        self.client.post(reverse("visit_start", args=[self.visit.pk]))
        self.client.post(reverse("visit_add_prescription_item", args=[self.visit.pk]), {
            "drug": self.drug.pk, "dosage": "1 tablet", "frequency": "once daily",
            "duration": "3 days", "instructions": "",
        })

        self.client.post(reverse("visit_complete", args=[self.visit.pk]))

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.WAITING_PHARMACY)
