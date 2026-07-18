from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from ..models import (
    Appointment,
    Department,
    Drug,
    Hospital,
    Notification,
    Patient,
    Prescription,
    PrescriptionItem,
    User,
    Visit,
)
from ..tenancy import reset_current_hospital, set_current_hospital


class PatientAPITests(TestCase):
    def setUp(self):
        self.hospital = Hospital.objects.create(name="API Test Hospital", subdomain="apitest")
        token = set_current_hospital(self.hospital)

        self.department = Department.objects.create(name="General Medicine")
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.patient_user = User.objects.create_user(
            username="patient1", password="pass1234", role=User.Role.PATIENT
        )
        self.patient = Patient.objects.create(
            full_name="API Patient", gender="F", date_of_birth="1990-01-01",
            phone="0700000099", patient_number="P-API-1", user=self.patient_user,
        )
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.COMPLETED,
        )
        self.drug = Drug.objects.create(
            name="Amoxicillin", category="Antibiotic", strength="500mg", unit_price=10
        )
        self.prescription = Prescription.objects.create(
            visit=self.visit, doctor=self.doctor, patient=self.patient
        )
        self.dispensed_item = PrescriptionItem.objects.create(
            prescription=self.prescription, drug=self.drug, quantity=10,
            dosage="1 tab", frequency="daily", duration="10 days",
            dispensed=True, dispensed_at=timezone.now(), dispensed_by=self.doctor,
        )
        # Left active for the whole test (not reset immediately) so object
        # creation directly in test methods — not just here in setUp — is
        # still tenant-scoped correctly. See TenantTestCase in tests.py for
        # the same pattern.
        self.addCleanup(reset_current_hospital, token)

        self.client = APIClient(HTTP_HOST=f"apitest.{settings.BASE_DOMAIN}")

    def _login(self, username="patient1", password="pass1234"):
        response = self.client.post(
            reverse("api_login"), {"username": username, "password": password}, format="json"
        )
        return response

    def _authenticate(self):
        response = self._login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return response

    def test_patient_login_returns_role_and_patient_id(self):
        response = self._login()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["role"], "PATIENT")
        self.assertEqual(response.data["patient_id"], self.patient.pk)

    def test_non_patient_login_rejected(self):
        response = self._login(username="doc1", password="pass1234")

        self.assertEqual(response.status_code, 401)

    def test_wrong_password_rejected(self):
        response = self._login(password="wrong")

        self.assertEqual(response.status_code, 401)

    def test_dashboard_requires_authentication(self):
        response = self.client.get(reverse("api_patient_dashboard"))

        self.assertEqual(response.status_code, 401)

    def test_dashboard_returns_own_data(self):
        self._authenticate()

        response = self.client.get(reverse("api_patient_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["patient"]["patient_number"], "P-API-1")

    def test_appointment_cancel(self):
        self._authenticate()
        appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now() + timedelta(days=1),
            status=Appointment.Status.SCHEDULED,
        )

        response = self.client.post(
            reverse("api_patient_appointment_cancel", args=[appointment.pk])
        )

        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CANCELLED)

    def test_appointment_cancel_for_other_patient_404s(self):
        self._authenticate()
        other_patient = Patient.objects.create(
            full_name="Other", gender="M", date_of_birth="1985-01-01",
            phone="0700000098", patient_number="P-API-2",
        )
        appointment = Appointment.objects.create(
            patient=other_patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now() + timedelta(days=1),
            status=Appointment.Status.SCHEDULED,
        )

        response = self.client.post(
            reverse("api_patient_appointment_cancel", args=[appointment.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_telemedicine_request_and_list(self):
        self._authenticate()

        create_response = self.client.post(
            reverse("api_patient_telemedicine"),
            {
                "department": self.department.pk,
                "appointment_date": (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": "Follow up",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data["consultation_type"], "TELEMEDICINE")

        list_response = self.client.get(reverse("api_patient_telemedicine"))
        self.assertEqual(len(list_response.data), 1)

    def test_telemedicine_rejects_past_date(self):
        self._authenticate()

        response = self.client.post(
            reverse("api_patient_telemedicine"),
            {
                "department": self.department.pk,
                "appointment_date": (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": "Follow up",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            Appointment.objects.filter(patient=self.patient, consultation_type="TELEMEDICINE").exists()
        )

    def test_refill_request_flow(self):
        self._authenticate()

        list_response = self.client.get(reverse("api_patient_refills"))
        self.assertEqual(len(list_response.data["eligible_items"]), 1)

        request_response = self.client.post(
            reverse("api_patient_request_refill", args=[self.dispensed_item.pk])
        )
        self.assertEqual(request_response.status_code, 201)
        self.assertEqual(request_response.data["status"], "PENDING")

        duplicate_response = self.client.post(
            reverse("api_patient_request_refill", args=[self.dispensed_item.pk])
        )
        self.assertEqual(duplicate_response.status_code, 400)

    def test_notifications_list_and_mark_all_read(self):
        self._authenticate()
        Notification.objects.create(user=self.patient_user, title="First")
        Notification.objects.create(user=self.patient_user, title="Second")

        list_response = self.client.get(reverse("api_patient_notifications"))
        self.assertEqual(len(list_response.data), 2)

        mark_response = self.client.post(reverse("api_patient_notifications_mark_all_read"))
        self.assertEqual(mark_response.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(user=self.patient_user, is_read=False).count(), 0
        )

    def test_emergency_alert_create(self):
        self._authenticate()

        response = self.client.post(
            reverse("api_patient_emergency_alert"),
            {"severity": "CRITICAL", "details": "Chest pain", "share_location": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.patient.emergency_alerts.count(), 1)

    def test_emergency_alert_rejects_invalid_severity(self):
        self._authenticate()

        response = self.client.post(
            reverse("api_patient_emergency_alert"), {"severity": "NOT_REAL"}, format="json"
        )

        self.assertEqual(response.status_code, 400)

    def test_change_password(self):
        self._authenticate()

        response = self.client.post(
            reverse("api_patient_change_password"),
            {
                "old_password": "pass1234",
                "new_password1": "N3wStrongPass!",
                "new_password2": "N3wStrongPass!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.patient_user.refresh_from_db()
        self.assertTrue(self.patient_user.check_password("N3wStrongPass!"))

    def test_message_send_and_thread(self):
        self._authenticate()

        send_response = self.client.post(
            reverse("api_patient_messages"),
            {"doctor": self.doctor.pk, "body": "Question about my prescription"},
            format="json",
        )
        self.assertEqual(send_response.status_code, 201)

        thread_response = self.client.get(
            reverse("api_patient_message_thread", args=[self.doctor.pk])
        )
        self.assertEqual(len(thread_response.data), 1)

    def test_message_to_untreating_doctor_rejected(self):
        self._authenticate()
        other_doctor = User.objects.create_user(
            username="doc2", password="pass1234", role=User.Role.DOCTOR
        )

        response = self.client.post(
            reverse("api_patient_messages"),
            {"doctor": other_doctor.pk, "body": "Hello"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_records_lab_results_invoices_smoke(self):
        self._authenticate()

        self.assertEqual(self.client.get(reverse("api_patient_records")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api_patient_lab_results")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api_patient_invoices")).status_code, 200)


class PatientAPITenantIsolationTests(TestCase):
    """The API is a new surface added after the multi-tenant conversion —
    worth its own isolation check rather than assuming it inherited safety
    for free."""

    def setUp(self):
        self.hospital_a = Hospital.objects.create(name="Hospital A", subdomain="api-a")
        self.hospital_b = Hospital.objects.create(name="Hospital B", subdomain="api-b")

        token = set_current_hospital(self.hospital_a)
        self.patient_user_a = User.objects.create_user(
            username="patient1", password="pass-a", role=User.Role.PATIENT
        )
        Patient.objects.create(
            full_name="Hospital A Patient", gender="F", date_of_birth="1990-01-01",
            phone="0700000000", patient_number="P-A-1", user=self.patient_user_a,
        )
        reset_current_hospital(token)

        token = set_current_hospital(self.hospital_b)
        self.patient_user_b = User.objects.create_user(
            username="patient1", password="pass-b", role=User.Role.PATIENT
        )
        Patient.objects.create(
            full_name="Hospital B Patient", gender="M", date_of_birth="1991-01-01",
            phone="0700000001", patient_number="P-B-1", user=self.patient_user_b,
        )
        reset_current_hospital(token)

        self.client_a = APIClient(HTTP_HOST=f"api-a.{settings.BASE_DOMAIN}")

    def test_same_username_login_scoped_to_own_hospital(self):
        response = self.client_a.post(
            reverse("api_login"), {"username": "patient1", "password": "pass-b"}, format="json"
        )

        self.assertEqual(response.status_code, 401)

    def test_dashboard_never_returns_other_hospitals_patient(self):
        login = self.client_a.post(
            reverse("api_login"), {"username": "patient1", "password": "pass-a"}, format="json"
        )
        self.client_a.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = self.client_a.get(reverse("api_patient_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["patient"]["full_name"], "Hospital A Patient")
