import json
import re
from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Appointment,
    AuditLog,
    Bed,
    Department,
    Drug,
    EmergencyAlert,
    Hospital,
    LabOrder,
    LabOrderItem,
    LabResult,
    LabTest,
    MedicalRecord,
    Message,
    Notification,
    Patient,
    Payment,
    Prescription,
    PrescriptionItem,
    QueueTicket,
    RefillRequest,
    Service,
    Stock,
    StockTransaction,
    User,
    Visit,
    VisitInvoice,
    VitalSigns,
    Ward,
)
from .tenancy import reset_current_hospital, set_current_hospital


class TenantTestCase(TestCase):
    """
    Shared base for every workflow TestCase below: creates a Hospital tenant
    and points self.client at its subdomain (so requests resolve it through
    the real TenantMiddleware), and also sets the tenancy contextvar
    directly so ORM calls made outside self.client (setUp fixtures, direct
    assertions) land in the same tenant without needing hospital=... on
    every single call.
    """

    def setUp(self):
        super().setUp()
        self.hospital = Hospital.objects.create(name="Test Hospital", subdomain="test")
        self.client = Client(HTTP_HOST=f"test.{settings.BASE_DOMAIN}")
        token = set_current_hospital(self.hospital)
        self.addCleanup(reset_current_hospital, token)


class ReceptionWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
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


class DoctorWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
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
        record = MedicalRecord.objects.get(visit=self.visit)
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.doctor, action="RECORD_DIAGNOSIS",
                table_name=record._meta.db_table, record_id=record.pk,
            ).exists()
        )

        self.client.post(reverse("visit_add_prescription_item", args=[self.visit.pk]), {
            "drug": self.drug.pk, "quantity": "15", "dosage": "1 tablet", "frequency": "3x daily",
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
            "drug": self.drug.pk, "quantity": "9", "dosage": "1 tablet", "frequency": "once daily",
            "duration": "3 days", "instructions": "",
        })

        self.client.post(reverse("visit_complete", args=[self.visit.pk]))

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.WAITING_PHARMACY)


class PharmacyWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.pharmacist = User.objects.create_user(
            username="pharm1", password="pass1234", role=User.Role.PHARMACIST
        )
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.department = Department.objects.create(name="General Medicine")
        self.patient = Patient.objects.create(
            full_name="Needs Meds", gender="F", date_of_birth="1988-01-01",
            phone="0700000001", patient_number="P-200001",
        )
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_PHARMACY,
        )
        self.drug = Drug.objects.create(
            name="Amoxicillin", category="Antibiotic", strength="500mg", unit_price=10
        )
        self.prescription = Prescription.objects.create(
            visit=self.visit, doctor=self.doctor, patient=self.patient
        )
        self.item = PrescriptionItem.objects.create(
            prescription=self.prescription, drug=self.drug, quantity=20,
            dosage="1 tablet", frequency="3x daily", duration="5 days",
        )
        self.client.login(username="pharm1", password="pass1234")

    def test_non_pharmacist_denied(self):
        User.objects.create_user(username="nurse1", password="pass1234", role=User.Role.NURSE)
        self.client.logout()
        self.client.login(username="nurse1", password="pass1234")

        response = self.client.get(reverse("pharmacy_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dispense_deducts_fefo_across_batches(self):
        near_batch = Stock.objects.create(
            drug=self.drug, quantity=5, expiry_date=timezone.localdate() + timedelta(days=10),
            batch_number="NEAR",
        )
        far_batch = Stock.objects.create(
            drug=self.drug, quantity=30, expiry_date=timezone.localdate() + timedelta(days=200),
            batch_number="FAR",
        )

        response = self.client.post(
            reverse("dispense_prescription_item", args=[self.visit.pk, self.item.pk])
        )

        self.assertRedirects(response, reverse("prescription_detail", args=[self.visit.pk]))
        near_batch.refresh_from_db()
        far_batch.refresh_from_db()
        self.item.refresh_from_db()

        self.assertEqual(near_batch.quantity, 0)
        self.assertEqual(far_batch.quantity, 15)
        self.assertTrue(self.item.dispensed)
        self.assertEqual(self.item.dispensed_by, self.pharmacist)
        self.assertEqual(
            StockTransaction.objects.filter(
                drug=self.drug, type=StockTransaction.TransactionType.OUT
            ).count(),
            1,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.pharmacist, action="DISPENSE_PRESCRIPTION_ITEM",
                table_name=self.item._meta.db_table, record_id=self.item.pk,
            ).exists()
        )

    def test_insufficient_stock_rejects_dispense(self):
        Stock.objects.create(
            drug=self.drug, quantity=3, expiry_date=timezone.localdate() + timedelta(days=10),
            batch_number="ONLY",
        )

        self.client.post(reverse("dispense_prescription_item", args=[self.visit.pk, self.item.pk]))

        self.item.refresh_from_db()
        self.assertFalse(self.item.dispensed)
        self.assertEqual(Stock.objects.get(batch_number="ONLY").quantity, 3)
        self.assertFalse(StockTransaction.objects.filter(drug=self.drug).exists())

    def test_dispensing_all_items_completes_visit(self):
        Stock.objects.create(
            drug=self.drug, quantity=100, expiry_date=timezone.localdate() + timedelta(days=30),
            batch_number="B1",
        )

        self.client.post(reverse("dispense_prescription_item", args=[self.visit.pk, self.item.pk]))

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.COMPLETED)

    def test_dispensing_one_of_two_items_keeps_visit_waiting(self):
        other_drug = Drug.objects.create(
            name="Paracetamol", category="Analgesic", strength="500mg", unit_price=2
        )
        other_item = PrescriptionItem.objects.create(
            prescription=self.prescription, drug=other_drug, quantity=10,
            dosage="1 tablet", frequency="once daily", duration="3 days",
        )
        Stock.objects.create(
            drug=self.drug, quantity=100, expiry_date=timezone.localdate() + timedelta(days=30),
            batch_number="B1",
        )
        # No stock created for other_drug — that item cannot be dispensed yet.

        self.client.post(reverse("dispense_prescription_item", args=[self.visit.pk, self.item.pk]))

        self.visit.refresh_from_db()
        other_item.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.WAITING_PHARMACY)
        self.assertFalse(other_item.dispensed)

    def test_already_dispensed_item_cannot_be_dispensed_again(self):
        Stock.objects.create(
            drug=self.drug, quantity=100, expiry_date=timezone.localdate() + timedelta(days=30),
            batch_number="B1",
        )
        self.client.post(reverse("dispense_prescription_item", args=[self.visit.pk, self.item.pk]))
        stock_after_first = Stock.objects.get(batch_number="B1").quantity

        self.client.post(reverse("dispense_prescription_item", args=[self.visit.pk, self.item.pk]))

        self.assertEqual(Stock.objects.get(batch_number="B1").quantity, stock_after_first)
        self.assertEqual(
            StockTransaction.objects.filter(drug=self.drug).count(), 1
        )

    def test_cannot_dispense_when_visit_not_awaiting_pharmacy(self):
        self.visit.status = Visit.Status.WAITING_DOCTOR
        self.visit.save(update_fields=["status"])
        Stock.objects.create(
            drug=self.drug, quantity=100, expiry_date=timezone.localdate() + timedelta(days=30),
            batch_number="B1",
        )

        detail_response = self.client.get(reverse("prescription_detail", args=[self.visit.pk]))
        self.assertEqual(detail_response.status_code, 403)

        self.client.post(reverse("dispense_prescription_item", args=[self.visit.pk, self.item.pk]))
        self.item.refresh_from_db()
        self.assertFalse(self.item.dispensed)


class LabWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.lab_tech = User.objects.create_user(
            username="lab1", password="pass1234", role=User.Role.LAB
        )
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.department = Department.objects.create(name="General Medicine")
        self.patient = Patient.objects.create(
            full_name="Needs Tests", gender="M", date_of_birth="1979-01-01",
            phone="0700000002", patient_number="P-300001",
        )
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_LAB,
        )
        self.lab_order = LabOrder.objects.create(
            visit=self.visit, patient=self.patient, doctor=self.doctor
        )
        self.test_a = LabTest.objects.create(name="Full Blood Count", price=15)
        self.test_b = LabTest.objects.create(name="Malaria Test", price=10)
        self.item_a = LabOrderItem.objects.create(lab_order=self.lab_order, test=self.test_a)
        self.item_b = LabOrderItem.objects.create(lab_order=self.lab_order, test=self.test_b)
        self.client.login(username="lab1", password="pass1234")

    def _result_payload(self, item_pk, value="Normal", normal_range="0-10", remarks=""):
        return {
            f"{item_pk}-result_value": value,
            f"{item_pk}-normal_range": normal_range,
            f"{item_pk}-remarks": remarks,
        }

    def test_non_lab_role_denied(self):
        User.objects.create_user(username="nurse1", password="pass1234", role=User.Role.NURSE)
        self.client.logout()
        self.client.login(username="nurse1", password="pass1234")

        response = self.client.get(reverse("lab_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_recording_one_result_marks_order_processing_and_keeps_visit_waiting(self):
        response = self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_a.pk]),
            self._result_payload(self.item_a.pk),
        )

        self.assertRedirects(response, reverse("lab_order_detail", args=[self.visit.pk]))
        self.lab_order.refresh_from_db()
        self.visit.refresh_from_db()
        self.assertEqual(self.lab_order.status, LabOrder.Status.PROCESSING)
        self.assertEqual(self.visit.status, Visit.Status.WAITING_LAB)
        result = LabResult.objects.get(lab_order=self.lab_order, test=self.test_a)
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.lab_tech, action="RECORD_LAB_RESULT",
                table_name=result._meta.db_table, record_id=result.pk,
            ).exists()
        )

    def test_all_results_recorded_completes_order_and_routes_visit_to_completed(self):
        self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_a.pk]),
            self._result_payload(self.item_a.pk),
        )
        self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_b.pk]),
            self._result_payload(self.item_b.pk, value="Negative"),
        )

        self.lab_order.refresh_from_db()
        self.visit.refresh_from_db()
        self.assertEqual(self.lab_order.status, LabOrder.Status.COMPLETED)
        self.assertEqual(self.visit.status, Visit.Status.COMPLETED)

    def test_all_results_recorded_routes_to_waiting_pharmacy_if_prescribed(self):
        drug = Drug.objects.create(name="Amoxicillin", category="Antibiotic", strength="500mg", unit_price=10)
        prescription = Prescription.objects.create(
            visit=self.visit, doctor=self.doctor, patient=self.patient
        )
        PrescriptionItem.objects.create(
            prescription=prescription, drug=drug, quantity=10,
            dosage="1 tab", frequency="2x daily", duration="5 days",
        )

        self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_a.pk]),
            self._result_payload(self.item_a.pk),
        )
        self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_b.pk]),
            self._result_payload(self.item_b.pk),
        )

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.WAITING_PHARMACY)

    def test_duplicate_result_rejected(self):
        self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_a.pk]),
            self._result_payload(self.item_a.pk, value="Normal"),
        )

        self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_a.pk]),
            self._result_payload(self.item_a.pk, value="Changed"),
        )

        results = LabResult.objects.filter(lab_order=self.lab_order, test=self.test_a)
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().result_value, "Normal")

    def test_cannot_record_result_when_visit_not_awaiting_lab(self):
        self.visit.status = Visit.Status.WAITING_DOCTOR
        self.visit.save(update_fields=["status"])

        detail_response = self.client.get(reverse("lab_order_detail", args=[self.visit.pk]))
        self.assertEqual(detail_response.status_code, 403)

        self.client.post(
            reverse("record_lab_result", args=[self.visit.pk, self.item_a.pk]),
            self._result_payload(self.item_a.pk),
        )
        self.assertFalse(
            LabResult.objects.filter(lab_order=self.lab_order, test=self.test_a).exists()
        )


class CashierWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.cashier = User.objects.create_user(
            username="cash1", password="pass1234", role=User.Role.CASHIER
        )
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.department = Department.objects.create(name="General Medicine")
        self.patient = Patient.objects.create(
            full_name="Owes Money", gender="F", date_of_birth="1991-01-01",
            phone="0700000003", patient_number="P-400001",
        )
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.COMPLETED,
        )
        self.consultation_fee = Service.objects.create(
            name="Consultation Fee", service_type=Service.ServiceType.APPOINTMENT, price=20,
        )
        self.client.login(username="cash1", password="pass1234")

    def test_non_cashier_denied(self):
        User.objects.create_user(username="nurse1", password="pass1234", role=User.Role.NURSE)
        self.client.logout()
        self.client.login(username="nurse1", password="pass1234")

        response = self.client.get(reverse("cashier_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_visit_invoice_detail_lazily_creates_invoice(self):
        self.assertFalse(VisitInvoice.objects.filter(visit=self.visit).exists())

        response = self.client.get(reverse("visit_invoice_detail", args=[self.visit.pk]))

        self.assertEqual(response.status_code, 200)
        invoice = VisitInvoice.objects.get(visit=self.visit)
        self.assertEqual(invoice.total_amount, 0)
        self.assertEqual(invoice.status, VisitInvoice.Status.UNPAID)

    def test_add_charge_updates_total(self):
        response = self.client.post(reverse("add_invoice_item", args=[self.visit.pk]), {
            "service": self.consultation_fee.pk, "quantity": "2",
        })

        self.assertRedirects(response, reverse("visit_invoice_detail", args=[self.visit.pk]))
        invoice = VisitInvoice.objects.get(visit=self.visit)
        self.assertEqual(invoice.total_amount, 40)
        self.assertEqual(invoice.status, VisitInvoice.Status.UNPAID)

    def test_partial_payment_updates_status(self):
        self.client.post(reverse("add_invoice_item", args=[self.visit.pk]), {
            "service": self.consultation_fee.pk, "quantity": "5",  # total 100
        })
        invoice = VisitInvoice.objects.get(visit=self.visit)

        response = self.client.post(reverse("record_payment", args=[self.visit.pk]), {
            "amount_paid": "40", "method": Payment.PaymentMethod.CASH, "reference": "",
        })

        self.assertRedirects(response, reverse("visit_invoice_detail", args=[self.visit.pk]))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, VisitInvoice.Status.PARTIAL)
        self.assertEqual(invoice.amount_paid, 40)
        self.assertEqual(invoice.balance_due, 60)
        payment = Payment.objects.get(invoice=invoice)
        self.assertTrue(payment.receipt_number.startswith("RCPT-"))
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.cashier, action="RECORD_PAYMENT",
                table_name=payment._meta.db_table, record_id=payment.pk,
            ).exists()
        )

    def test_full_payment_marks_paid(self):
        self.client.post(reverse("add_invoice_item", args=[self.visit.pk]), {
            "service": self.consultation_fee.pk, "quantity": "1",  # total 20
        })

        self.client.post(reverse("record_payment", args=[self.visit.pk]), {
            "amount_paid": "20", "method": Payment.PaymentMethod.CASH, "reference": "",
        })

        invoice = VisitInvoice.objects.get(visit=self.visit)
        self.assertEqual(invoice.status, VisitInvoice.Status.PAID)
        self.assertEqual(invoice.balance_due, 0)

    def test_overpayment_rejected(self):
        self.client.post(reverse("add_invoice_item", args=[self.visit.pk]), {
            "service": self.consultation_fee.pk, "quantity": "1",  # total 20
        })

        self.client.post(reverse("record_payment", args=[self.visit.pk]), {
            "amount_paid": "999", "method": Payment.PaymentMethod.CASH, "reference": "",
        })

        invoice = VisitInvoice.objects.get(visit=self.visit)
        self.assertEqual(invoice.status, VisitInvoice.Status.UNPAID)
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())

    def test_payment_rejected_once_fully_paid(self):
        self.client.post(reverse("add_invoice_item", args=[self.visit.pk]), {
            "service": self.consultation_fee.pk, "quantity": "1",  # total 20
        })
        self.client.post(reverse("record_payment", args=[self.visit.pk]), {
            "amount_paid": "20", "method": Payment.PaymentMethod.CASH, "reference": "",
        })

        self.client.post(reverse("record_payment", args=[self.visit.pk]), {
            "amount_paid": "5", "method": Payment.PaymentMethod.CASH, "reference": "",
        })

        invoice = VisitInvoice.objects.get(visit=self.visit)
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)
        self.assertEqual(invoice.amount_paid, 20)

    def test_zero_or_negative_payment_rejected(self):
        self.client.post(reverse("add_invoice_item", args=[self.visit.pk]), {
            "service": self.consultation_fee.pk, "quantity": "1",
        })

        self.client.post(reverse("record_payment", args=[self.visit.pk]), {
            "amount_paid": "0", "method": Payment.PaymentMethod.CASH, "reference": "",
        })

        invoice = VisitInvoice.objects.get(visit=self.visit)
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())
        self.assertEqual(invoice.status, VisitInvoice.Status.UNPAID)


class NurseWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.nurse = User.objects.create_user(
            username="nurse1", password="pass1234", role=User.Role.NURSE
        )
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.department = Department.objects.create(name="General Medicine")
        self.patient = Patient.objects.create(
            full_name="Waiting Room", gender="F", date_of_birth="1995-01-01",
            phone="0700000004", patient_number="P-500001",
        )
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_DOCTOR,
        )
        self.client.login(username="nurse1", password="pass1234")

    def _vitals_payload(self, **overrides):
        payload = {
            "temperature": "37.2", "pulse_rate": "70",
            "blood_pressure": "120/80", "weight": "65", "height": "168",
        }
        payload.update(overrides)
        return payload

    def test_non_nurse_denied(self):
        User.objects.create_user(
            username="pharm1", password="pass1234", role=User.Role.PHARMACIST
        )
        self.client.logout()
        self.client.login(username="pharm1", password="pass1234")

        response = self.client.get(reverse("nurse_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_flags_visits_missing_vitals(self):
        other_patient = Patient.objects.create(
            full_name="Already Triaged", gender="M", date_of_birth="1992-01-01",
            phone="0700000005", patient_number="P-500002",
        )
        other_visit = Visit.objects.create(
            patient=other_patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_DOCTOR,
        )
        VitalSigns.objects.create(
            visit=other_visit, temperature=36.9, pulse_rate=68,
            blood_pressure="118/76", weight=70, height=175, recorded_by=self.nurse,
        )

        response = self.client.get(reverse("nurse_dashboard"))

        visits_by_id = {v.pk: v for v in response.context["visits"]}
        self.assertFalse(visits_by_id[self.visit.pk].has_vitals)
        self.assertTrue(visits_by_id[other_visit.pk].has_vitals)

    def test_record_vitals_creates_entry(self):
        response = self.client.post(
            reverse("nurse_record_vitals", args=[self.visit.pk]), self._vitals_payload()
        )

        self.assertRedirects(response, reverse("nurse_triage", args=[self.visit.pk]))
        vitals = VitalSigns.objects.get(visit=self.visit)
        self.assertEqual(vitals.recorded_by, self.nurse)
        self.assertEqual(str(vitals.blood_pressure), "120/80")

    def test_multiple_readings_allowed(self):
        self.client.post(
            reverse("nurse_record_vitals", args=[self.visit.pk]),
            self._vitals_payload(temperature="37.0"),
        )
        self.client.post(
            reverse("nurse_record_vitals", args=[self.visit.pk]),
            self._vitals_payload(temperature="38.5"),
        )

        self.assertEqual(VitalSigns.objects.filter(visit=self.visit).count(), 2)

    def test_cannot_triage_once_doctor_starts_consultation(self):
        self.visit.status = Visit.Status.IN_CONSULTATION
        self.visit.save(update_fields=["status"])

        detail_response = self.client.get(reverse("nurse_triage", args=[self.visit.pk]))
        self.assertEqual(detail_response.status_code, 403)

        self.client.post(reverse("nurse_record_vitals", args=[self.visit.pk]), self._vitals_payload())
        self.assertFalse(VitalSigns.objects.filter(visit=self.visit).exists())

    def test_visit_no_longer_on_dashboard_after_consultation_starts(self):
        self.visit.status = Visit.Status.IN_CONSULTATION
        self.visit.save(update_fields=["status"])

        response = self.client.get(reverse("nurse_dashboard"))

        visit_ids = [v.pk for v in response.context["visits"]]
        self.assertNotIn(self.visit.pk, visit_ids)


class StockManagerWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.stock_manager = User.objects.create_user(
            username="stock1", password="pass1234", role=User.Role.STOCK_MANAGER
        )
        self.drug = Drug.objects.create(
            name="Amoxicillin", category="Antibiotic", strength="500mg", unit_price=10
        )
        self.client.login(username="stock1", password="pass1234")

    def test_non_stock_manager_denied(self):
        User.objects.create_user(username="nurse1", password="pass1234", role=User.Role.NURSE)
        self.client.logout()
        self.client.login(username="nurse1", password="pass1234")

        response = self.client.get(reverse("stock_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_aggregates_total_quantity_across_batches(self):
        Stock.objects.create(
            drug=self.drug, quantity=10, batch_number="A1",
            expiry_date=timezone.localdate() + timedelta(days=60),
        )
        Stock.objects.create(
            drug=self.drug, quantity=15, batch_number="A2",
            expiry_date=timezone.localdate() + timedelta(days=90),
        )

        response = self.client.get(reverse("stock_dashboard"))

        drugs_by_id = {d.pk: d for d in response.context["drugs"]}
        self.assertEqual(drugs_by_id[self.drug.pk].total_quantity, 25)

    def test_receive_stock_creates_new_batch(self):
        expiry = (timezone.localdate() + timedelta(days=60)).isoformat()

        response = self.client.post(reverse("receive_stock", args=[self.drug.pk]), {
            "batch_number": "NEWBATCH", "quantity": "40", "expiry_date": expiry,
        })

        self.assertRedirects(response, reverse("drug_stock_detail", args=[self.drug.pk]))
        batch = Stock.objects.get(drug=self.drug, batch_number="NEWBATCH")
        self.assertEqual(batch.quantity, 40)
        txn = StockTransaction.objects.get(drug=self.drug, type=StockTransaction.TransactionType.IN)
        self.assertEqual(txn.quantity, 40)

    def test_receive_stock_tops_up_existing_batch(self):
        expiry = timezone.localdate() + timedelta(days=60)
        Stock.objects.create(
            drug=self.drug, quantity=10, batch_number="TOPUP", expiry_date=expiry
        )

        self.client.post(reverse("receive_stock", args=[self.drug.pk]), {
            "batch_number": "TOPUP", "quantity": "5", "expiry_date": expiry.isoformat(),
        })

        self.assertEqual(Stock.objects.filter(drug=self.drug, batch_number="TOPUP").count(), 1)
        self.assertEqual(Stock.objects.get(drug=self.drug, batch_number="TOPUP").quantity, 15)

    def test_receive_stock_rejects_past_expiry(self):
        past = (timezone.localdate() - timedelta(days=1)).isoformat()

        self.client.post(reverse("receive_stock", args=[self.drug.pk]), {
            "batch_number": "OLDBATCH", "quantity": "10", "expiry_date": past,
        })

        self.assertFalse(Stock.objects.filter(drug=self.drug, batch_number="OLDBATCH").exists())

    def test_adjust_stock_reduces_quantity_and_logs_transaction(self):
        Stock.objects.create(
            drug=self.drug, quantity=20, batch_number="A1",
            expiry_date=timezone.localdate() + timedelta(days=60),
        )
        batch = Stock.objects.get(drug=self.drug, batch_number="A1")

        response = self.client.post(reverse("adjust_stock", args=[self.drug.pk]), {
            "batch": batch.pk, "quantity": "5", "reason": "Damaged in storage",
        })

        self.assertRedirects(response, reverse("drug_stock_detail", args=[self.drug.pk]))
        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 15)
        txn = StockTransaction.objects.get(drug=self.drug, type=StockTransaction.TransactionType.OUT)
        self.assertEqual(txn.quantity, 5)
        self.assertEqual(txn.reason, "Damaged in storage")

    def test_adjust_stock_rejects_over_removal(self):
        Stock.objects.create(
            drug=self.drug, quantity=5, batch_number="A1",
            expiry_date=timezone.localdate() + timedelta(days=60),
        )
        batch = Stock.objects.get(drug=self.drug, batch_number="A1")

        self.client.post(reverse("adjust_stock", args=[self.drug.pk]), {
            "batch": batch.pk, "quantity": "10", "reason": "Miscount",
        })

        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 5)
        self.assertFalse(StockTransaction.objects.filter(drug=self.drug).exists())

    def test_adjust_stock_requires_reason(self):
        Stock.objects.create(
            drug=self.drug, quantity=5, batch_number="A1",
            expiry_date=timezone.localdate() + timedelta(days=60),
        )
        batch = Stock.objects.get(drug=self.drug, batch_number="A1")

        self.client.post(reverse("adjust_stock", args=[self.drug.pk]), {
            "batch": batch.pk, "quantity": "1", "reason": "",
        })

        batch.refresh_from_db()
        self.assertEqual(batch.quantity, 5)


class AdminDashboardTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_user(
            username="admin1", password="pass1234", role=User.Role.ADMIN
        )
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.department = Department.objects.create(name="General Medicine")
        self.client.login(username="admin1", password="pass1234")

    def test_non_admin_denied(self):
        User.objects.create_user(username="nurse1", password="pass1234", role=User.Role.NURSE)
        self.client.logout()
        self.client.login(username="nurse1", password="pass1234")

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_kpi_counts_reflect_real_data(self):
        patient = Patient.objects.create(
            full_name="Dashboard Patient", gender="F", date_of_birth="1990-01-01",
            phone="0700000006", patient_number="P-600001",
        )
        Appointment.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now(),
        )
        visit = Visit.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_DOCTOR,
        )
        invoice = VisitInvoice.objects.create(visit=visit, patient=patient, total_amount=100)
        Payment.objects.create(
            receipt_number="RCPT-TEST-1", invoice=invoice, amount_paid=40,
            method=Payment.PaymentMethod.CASH,
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.context["total_patients"], 1)
        self.assertGreaterEqual(response.context["todays_appointments"], 1)
        self.assertGreaterEqual(response.context["active_visits"], 1)
        self.assertEqual(response.context["todays_revenue"], 40)

    def test_appointments_delta_calculation(self):
        patient = Patient.objects.create(
            full_name="Delta Patient", gender="M", date_of_birth="1985-01-01",
            phone="0700000007", patient_number="P-600002",
        )
        yesterday = timezone.now() - timedelta(days=1)
        Appointment.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            appointment_date=yesterday,
        )
        Appointment.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now(),
        )
        Appointment.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now(),
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.context["todays_appointments"], 2)
        self.assertEqual(response.context["appointments_delta"], 100)

    def test_ward_occupancy_percentage(self):
        ward = Ward.objects.create(name="General Ward", department=self.department, capacity=4)
        for i in range(4):
            Bed.objects.create(ward=ward, bed_number=str(i + 1), is_occupied=(i < 2))

        response = self.client.get(reverse("admin_dashboard"))

        wards_by_id = {w.pk: w for w in response.context["wards"]}
        self.assertEqual(wards_by_id[ward.pk].occupied_count, 2)
        self.assertEqual(wards_by_id[ward.pk].bed_count, 4)
        self.assertEqual(wards_by_id[ward.pk].occupancy_pct, 50)

    def test_department_active_visit_count_excludes_completed(self):
        patient = Patient.objects.create(
            full_name="Dept Patient", gender="F", date_of_birth="1988-01-01",
            phone="0700000008", patient_number="P-600003",
        )
        Visit.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_DOCTOR,
        )
        Visit.objects.create(
            patient=patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.COMPLETED,
        )

        response = self.client.get(reverse("admin_dashboard"))

        departments_by_id = {d.pk: d for d in response.context["departments"]}
        self.assertEqual(departments_by_id[self.department.pk].active_visit_count, 1)

    def test_low_stock_drug_counted(self):
        Drug.objects.create(name="Zero Stock Drug", category="Test", strength="1mg", unit_price=1)

        response = self.client.get(reverse("admin_dashboard"))

        self.assertGreaterEqual(response.context["low_stock_drugs"], 1)


class AdminStaffAccessSignalTests(TenantTestCase):
    def test_creating_admin_user_grants_staff_and_group_access(self):
        user = User.objects.create_user(
            username="new_admin", password="pass1234", role=User.Role.ADMIN
        )

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(name="Hospital Admins").exists())
        self.assertTrue(user.has_perm("hospital.view_drug"))
        self.assertTrue(user.has_perm("hospital.add_ward"))
        self.assertTrue(user.has_perm("hospital.view_auditlog"))

    def test_admin_group_never_grants_auditlog_delete(self):
        User.objects.create_user(username="new_admin2", password="pass1234", role=User.Role.ADMIN)

        user = User.objects.get(username="new_admin2")
        self.assertFalse(user.has_perm("hospital.delete_auditlog"))

    def test_promoting_existing_user_to_admin_grants_access_retroactively(self):
        user = User.objects.create_user(
            username="future_admin", password="pass1234", role=User.Role.RECEPTIONIST
        )
        self.assertFalse(user.is_staff)

        user.role = User.Role.ADMIN
        user.save()

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(name="Hospital Admins").exists())

    def test_non_admin_user_is_not_granted_staff_access(self):
        user = User.objects.create_user(
            username="regular_nurse", password="pass1234", role=User.Role.NURSE
        )

        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.groups.filter(name="Hospital Admins").exists())


class PatientWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.department = Department.objects.create(name="General Medicine")
        self.doctor = User.objects.create_user(
            username="doc1", password="pass1234", role=User.Role.DOCTOR
        )
        self.other_doctor = User.objects.create_user(
            username="doc2", password="pass1234", role=User.Role.DOCTOR
        )

        self.patient_user = User.objects.create_user(
            username="patient1", password="pass1234", role=User.Role.PATIENT
        )
        self.patient = Patient.objects.create(
            full_name="Portal Patient", gender="F", date_of_birth="1990-01-01",
            phone="0700000010", patient_number="P-300001", user=self.patient_user,
        )

        self.other_patient = Patient.objects.create(
            full_name="Other Patient", gender="M", date_of_birth="1985-01-01",
            phone="0700000011", patient_number="P-300002",
        )

        self.receptionist = User.objects.create_user(
            username="recep1", password="pass1234", role=User.Role.RECEPTIONIST
        )

        self.drug = Drug.objects.create(
            name="Amlodipine", category="Cardiovascular", strength="5mg", unit_price=5
        )

        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.COMPLETED,
        )
        self.prescription = Prescription.objects.create(
            visit=self.visit, doctor=self.doctor, patient=self.patient
        )
        self.dispensed_item = PrescriptionItem.objects.create(
            prescription=self.prescription, drug=self.drug, quantity=30,
            dosage="1 tablet", frequency="once daily", duration="30 days",
            dispensed=True, dispensed_at=timezone.now(), dispensed_by=self.doctor,
        )

        self.client.login(username="patient1", password="pass1234")

    def test_non_patient_denied_dashboard(self):
        self.client.logout()
        self.client.login(username="doc1", password="pass1234")

        response = self.client.get(reverse("patient_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_unlinked_patient_sees_friendly_message_not_crash(self):
        User.objects.create_user(username="orphan", password="pass1234", role=User.Role.PATIENT)
        self.client.logout()
        self.client.login(username="orphan", password="pass1234")

        response = self.client.get(reverse("patient_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["patient"])

    def test_telemedicine_request_creates_appointment_for_own_patient(self):
        appointment_date = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")

        response = self.client.post(reverse("telemedicine_start"), {
            "doctor": self.doctor.pk,
            "department": self.department.pk,
            "appointment_date": appointment_date,
            "reason": "Follow-up",
        })

        self.assertRedirects(response, reverse("telemedicine_start"))
        appointment = Appointment.objects.get(patient=self.patient)
        self.assertEqual(appointment.consultation_type, Appointment.ConsultationType.TELEMEDICINE)
        self.assertEqual(appointment.meeting_link, "")

    def test_telemedicine_history_only_shows_own_appointments(self):
        mine = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now() - timedelta(days=1),
            status=Appointment.Status.COMPLETED,
            consultation_type=Appointment.ConsultationType.TELEMEDICINE,
        )
        Appointment.objects.create(
            patient=self.other_patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now() - timedelta(days=1),
            status=Appointment.Status.COMPLETED,
            consultation_type=Appointment.ConsultationType.TELEMEDICINE,
        )

        response = self.client.get(reverse("telemedicine_history"))

        past = list(response.context["past_appointments"])
        self.assertEqual(past, [mine])

    def test_request_refill_creates_pending_request(self):
        response = self.client.post(reverse("request_refill", args=[self.dispensed_item.pk]))

        self.assertRedirects(response, reverse("prescription_refill"))
        refill_request = RefillRequest.objects.get(prescription_item=self.dispensed_item)
        self.assertEqual(refill_request.status, RefillRequest.Status.PENDING)
        self.assertEqual(refill_request.patient, self.patient)

    def test_request_refill_for_other_patients_item_404s(self):
        other_prescription = Prescription.objects.create(
            visit=Visit.objects.create(
                patient=self.other_patient, doctor=self.doctor, department=self.department,
                visit_type=Visit.VisitType.OPD, status=Visit.Status.COMPLETED,
            ),
            doctor=self.doctor, patient=self.other_patient,
        )
        other_item = PrescriptionItem.objects.create(
            prescription=other_prescription, drug=self.drug, quantity=10,
            dosage="1 tablet", frequency="once daily", duration="10 days",
            dispensed=True, dispensed_at=timezone.now(), dispensed_by=self.doctor,
        )

        response = self.client.post(reverse("request_refill", args=[other_item.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(RefillRequest.objects.filter(prescription_item=other_item).exists())

    def test_duplicate_pending_refill_request_rejected(self):
        self.client.post(reverse("request_refill", args=[self.dispensed_item.pk]))

        self.client.post(reverse("request_refill", args=[self.dispensed_item.pk]))

        self.assertEqual(
            RefillRequest.objects.filter(prescription_item=self.dispensed_item).count(), 1
        )

    def test_doctor_refill_queue_only_shows_own_prescriptions(self):
        RefillRequest.objects.create(patient=self.patient, prescription_item=self.dispensed_item)

        self.client.logout()
        self.client.login(username="doc2", password="pass1234")
        response = self.client.get(reverse("doctor_dashboard"))

        self.assertEqual(len(response.context["pending_refill_requests"]), 0)

    def test_refill_request_approve_creates_waiting_pharmacy_visit_reaching_pharmacy_dashboard(self):
        refill_request = RefillRequest.objects.create(
            patient=self.patient, prescription_item=self.dispensed_item
        )
        self.client.logout()
        self.client.login(username="doc1", password="pass1234")

        response = self.client.post(reverse("refill_request_approve", args=[refill_request.pk]))

        self.assertRedirects(response, reverse("doctor_dashboard"))
        refill_request.refresh_from_db()
        self.assertEqual(refill_request.status, RefillRequest.Status.APPROVED)
        new_item = refill_request.new_prescription_item
        self.assertIsNotNone(new_item)
        new_visit = new_item.prescription.visit
        self.assertEqual(new_visit.status, Visit.Status.WAITING_PHARMACY)
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.doctor, action="APPROVE_REFILL_REQUEST",
                table_name=refill_request._meta.db_table, record_id=refill_request.pk,
            ).exists()
        )

        pharmacist = User.objects.create_user(
            username="pharm1", password="pass1234", role=User.Role.PHARMACIST
        )
        self.client.logout()
        self.client.login(username="pharm1", password="pass1234")
        pharmacy_response = self.client.get(reverse("pharmacy_dashboard"))
        self.assertIn(new_visit, list(pharmacy_response.context["visits"]))

    def test_refill_request_deny_requires_reason(self):
        refill_request = RefillRequest.objects.create(
            patient=self.patient, prescription_item=self.dispensed_item
        )
        self.client.logout()
        self.client.login(username="doc1", password="pass1234")

        response = self.client.post(reverse("refill_request_deny", args=[refill_request.pk]), {})

        self.assertRedirects(response, reverse("doctor_dashboard"))
        refill_request.refresh_from_db()
        self.assertEqual(refill_request.status, RefillRequest.Status.PENDING)

        response = self.client.post(
            reverse("refill_request_deny", args=[refill_request.pk]), {"reason": "Needs a checkup first"}
        )
        refill_request.refresh_from_db()
        self.assertEqual(refill_request.status, RefillRequest.Status.DENIED)
        self.assertEqual(refill_request.denial_reason, "Needs a checkup first")
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.doctor, action="DENY_REFILL_REQUEST",
                table_name=refill_request._meta.db_table, record_id=refill_request.pk,
            ).exists()
        )

    def test_doctor_who_did_not_prescribe_denied_on_approve(self):
        refill_request = RefillRequest.objects.create(
            patient=self.patient, prescription_item=self.dispensed_item
        )
        self.client.logout()
        self.client.login(username="doc2", password="pass1234")

        response = self.client.post(reverse("refill_request_approve", args=[refill_request.pk]))

        self.assertEqual(response.status_code, 403)

    def test_records_download_renders_own_data_only(self):
        MedicalRecord.objects.create(
            visit=self.visit, patient=self.patient, doctor=self.doctor, diagnosis="Hypertension"
        )

        response = self.client.get(reverse("records_download"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["visits"]), [self.visit])

    def test_patient_can_cancel_own_scheduled_appointment(self):
        appointment = Appointment.objects.create(
            patient=self.patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now() + timedelta(days=1),
            status=Appointment.Status.SCHEDULED,
        )

        response = self.client.post(reverse("patient_appointment_cancel", args=[appointment.pk]))

        self.assertRedirects(response, reverse("patient_dashboard"))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CANCELLED)

    def test_patient_cannot_cancel_other_patients_appointment(self):
        appointment = Appointment.objects.create(
            patient=self.other_patient, doctor=self.doctor, department=self.department,
            appointment_date=timezone.now() + timedelta(days=1),
            status=Appointment.Status.SCHEDULED,
        )

        response = self.client.post(reverse("patient_appointment_cancel", args=[appointment.pk]))

        self.assertEqual(response.status_code, 404)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)

    def test_notifications_mark_all_read(self):
        Notification.objects.create(user=self.patient_user, title="First")
        Notification.objects.create(user=self.patient_user, title="Second")

        response = self.client.post(reverse("notifications_mark_all_read"))

        self.assertRedirects(response, reverse("patient_dashboard"))
        self.assertEqual(Notification.objects.filter(user=self.patient_user, is_read=False).count(), 0)

    def test_emergency_alert_create_without_location(self):
        response = self.client.post(
            reverse("emergency_alert_create"),
            data=json.dumps({
                "severity": "CRITICAL", "share_location": False, "details": "Chest pain",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        alert = EmergencyAlert.objects.get(patient=self.patient)
        self.assertEqual(alert.severity, EmergencyAlert.Severity.CRITICAL)
        self.assertEqual(alert.status, EmergencyAlert.Status.NEW)
        self.assertIsNone(alert.latitude)

    def test_emergency_alert_create_with_location(self):
        response = self.client.post(
            reverse("emergency_alert_create"),
            data=json.dumps({
                "severity": "URGENT", "share_location": True, "details": "",
                "latitude": 1.234567, "longitude": 36.123456,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        alert = EmergencyAlert.objects.get(patient=self.patient)
        self.assertTrue(alert.has_location)

    def test_emergency_alert_create_rejects_invalid_severity(self):
        response = self.client.post(
            reverse("emergency_alert_create"),
            data=json.dumps({"severity": "NOT_A_LEVEL"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(EmergencyAlert.objects.exists())

    def test_reception_can_acknowledge_and_resolve_emergency_alert(self):
        alert = EmergencyAlert.objects.create(patient=self.patient, severity=EmergencyAlert.Severity.CRITICAL)
        self.client.logout()
        self.client.login(username="recep1", password="pass1234")

        response = self.client.post(reverse("emergency_alert_acknowledge", args=[alert.pk]))
        self.assertRedirects(response, reverse("reception_dashboard"))
        alert.refresh_from_db()
        self.assertEqual(alert.status, EmergencyAlert.Status.ACKNOWLEDGED)
        self.assertEqual(alert.acknowledged_by, self.receptionist)
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.receptionist, action="ACKNOWLEDGE_EMERGENCY_ALERT",
                table_name=alert._meta.db_table, record_id=alert.pk,
            ).exists()
        )

        response = self.client.post(reverse("emergency_alert_resolve", args=[alert.pk]))
        self.assertRedirects(response, reverse("reception_dashboard"))
        alert.refresh_from_db()
        self.assertEqual(alert.status, EmergencyAlert.Status.RESOLVED)
        self.assertTrue(
            AuditLog.objects.filter(
                user=self.receptionist, action="RESOLVE_EMERGENCY_ALERT",
                table_name=alert._meta.db_table, record_id=alert.pk,
            ).exists()
        )

    def test_patient_can_message_a_doctor_who_treated_them(self):
        response = self.client.post(reverse("patient_messages"), {
            "doctor": self.doctor.pk, "body": "Question about my prescription",
        })

        self.assertRedirects(response, reverse("patient_messages"))
        message = Message.objects.get(patient=self.patient)
        self.assertEqual(message.sender, self.patient_user)
        self.assertEqual(message.doctor, self.doctor)
        self.assertTrue(
            Notification.objects.filter(user=self.doctor, title__icontains="New message").exists()
        )

    def test_patient_cannot_message_a_doctor_who_never_treated_them(self):
        response = self.client.post(reverse("patient_messages"), {
            "doctor": self.other_doctor.pk, "body": "Hello",
        })

        # Invalid form (doctor outside the scoped queryset) re-renders inline,
        # same convention as appointment_create/telemedicine_start.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.exists())

    def test_patient_message_thread_403_for_doctor_who_never_treated_them(self):
        response = self.client.get(reverse("patient_message_thread", args=[self.other_doctor.pk]))

        self.assertEqual(response.status_code, 403)

    def test_doctor_reply_marks_patient_messages_read_and_notifies_patient(self):
        Message.objects.create(
            patient=self.patient, doctor=self.doctor, sender=self.patient_user, body="Hi doctor"
        )
        self.client.logout()
        self.client.login(username="doc1", password="pass1234")

        # GET marks the patient's message as read.
        self.client.get(reverse("doctor_message_thread", args=[self.patient.pk]))
        self.assertTrue(Message.objects.get(sender=self.patient_user).is_read)

        response = self.client.post(
            reverse("doctor_message_thread", args=[self.patient.pk]), {"body": "Take it easy"}
        )

        self.assertRedirects(response, reverse("doctor_message_thread", args=[self.patient.pk]))
        reply = Message.objects.get(sender=self.doctor)
        self.assertEqual(reply.patient, self.patient)
        self.assertTrue(
            Notification.objects.filter(user=self.patient_user, title__icontains="New message").exists()
        )

    def test_doctor_message_thread_403_for_patient_never_treated(self):
        self.client.logout()
        self.client.login(username="doc1", password="pass1234")

        response = self.client.get(reverse("doctor_message_thread", args=[self.other_patient.pk]))

        self.assertEqual(response.status_code, 403)

    def test_patient_can_change_own_password(self):
        response = self.client.post(reverse("patient_change_password"), {
            "old_password": "pass1234",
            "new_password1": "N3wStrongPass!",
            "new_password2": "N3wStrongPass!",
        })

        self.assertRedirects(
            response, f"{reverse('patient_dashboard')}#settings", fetch_redirect_response=False
        )
        self.patient_user.refresh_from_db()
        self.assertTrue(self.patient_user.check_password("N3wStrongPass!"))

        # Session stays authenticated (update_session_auth_hash) — dashboard still loads.
        dashboard_response = self.client.get(reverse("patient_dashboard"))
        self.assertEqual(dashboard_response.status_code, 200)

    def test_patient_change_password_rejects_wrong_current_password(self):
        response = self.client.post(reverse("patient_change_password"), {
            "old_password": "wrong-password",
            "new_password1": "N3wStrongPass!",
            "new_password2": "N3wStrongPass!",
        })

        self.assertRedirects(
            response, f"{reverse('patient_dashboard')}#settings", fetch_redirect_response=False
        )
        self.patient_user.refresh_from_db()
        self.assertTrue(self.patient_user.check_password("pass1234"))


class AuthWorkflowTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            username="authuser", password="pass1234", role=User.Role.DOCTOR, email="authuser@example.com"
        )

    def test_login_without_remember_me_expires_at_browser_close(self):
        self.client.post(reverse("login"), {"username": "authuser", "password": "pass1234"})

        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_login_with_remember_me_persists_session(self):
        self.client.post(reverse("login"), {
            "username": "authuser", "password": "pass1234", "remember_me": "on",
        })

        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.session.get_expiry_age(), 1209600)

    def test_password_reset_sends_email_and_new_password_works(self):
        response = self.client.post(reverse("password_reset"), {"email": "authuser@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("authuser@example.com", mail.outbox[0].to)

        match = re.search(r"/hospital/reset/(?P<uidb64>[\w-]+)/(?P<token>[\w-]+)/", mail.outbox[0].body)
        self.assertIsNotNone(match)

        confirm_url = reverse(
            "password_reset_confirm", kwargs={"uidb64": match.group("uidb64"), "token": match.group("token")}
        )
        get_response = self.client.get(confirm_url, follow=True)
        self.assertTrue(get_response.context["validlink"])

        post_response = self.client.post(get_response.wsgi_request.path, {
            "new_password1": "BrandNewPass1!", "new_password2": "BrandNewPass1!",
        })
        self.assertRedirects(post_response, reverse("password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNewPass1!"))

    def test_password_reset_for_unknown_email_sends_nothing_but_still_redirects(self):
        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_confirm_rejects_invalid_token(self):
        url = reverse("password_reset_confirm", kwargs={"uidb64": "invalid", "token": "invalid-token"})

        response = self.client.get(url, follow=True)

        self.assertFalse(response.context["validlink"])


class TenantIsolationTests(TestCase):
    """
    Proves the actual thing this SaaS conversion is for: two hospitals'
    staff, logins, and patient data are fully isolated from each other —
    distinct from every class above, which only proves each workflow still
    works *within* a single tenant.
    """

    def setUp(self):
        self.hospital_a = Hospital.objects.create(name="Hospital A", subdomain="hospital-a")
        self.hospital_b = Hospital.objects.create(name="Hospital B", subdomain="hospital-b")

        token = set_current_hospital(self.hospital_a)
        self.receptionist_a = User.objects.create_user(
            username="staff1", password="pass-a", role=User.Role.RECEPTIONIST
        )
        self.doctor_a = User.objects.create_user(
            username="doctor1", password="pass-a", role=User.Role.DOCTOR
        )
        self.patient_a = Patient.objects.create(
            full_name="Hospital A Patient", gender="M", date_of_birth="1990-01-01",
            phone="0700000000", patient_number="P-A-1",
        )
        reset_current_hospital(token)

        token = set_current_hospital(self.hospital_b)
        self.doctor_b = User.objects.create_user(
            username="doctor1", password="pass-b", role=User.Role.DOCTOR
        )
        self.department_b = Department.objects.create(name="General Medicine")
        self.patient_b = Patient.objects.create(
            full_name="Hospital B Patient", gender="F", date_of_birth="1991-01-01",
            phone="0700000001", patient_number="P-B-1",
        )
        self.visit_b = Visit.objects.create(
            patient=self.patient_b, doctor=self.doctor_b, department=self.department_b,
            visit_type=Visit.VisitType.OPD, status=Visit.Status.WAITING_DOCTOR,
        )
        reset_current_hospital(token)

        self.client_a = Client(HTTP_HOST=f"hospital-a.{settings.BASE_DOMAIN}")

    def test_same_username_in_two_hospitals_does_not_collide(self):
        self.assertNotEqual(self.doctor_a.pk, self.doctor_b.pk)
        self.assertEqual(self.doctor_a.username, self.doctor_b.username)

    def _login(self, client, username, password):
        # Client.login() bypasses HTTP/middleware entirely (it calls
        # authenticate() directly), so it never resolves a tenant — a real
        # POST through the login view is required to exercise
        # TenantMiddleware/host-based resolution honestly here.
        return client.post(reverse("login"), {"username": username, "password": password})

    def test_login_authenticates_against_the_right_hospital_only(self):
        self._login(self.client_a, "doctor1", "pass-a")
        self.assertEqual(self.client_a.session.get("_auth_user_id"), str(self.doctor_a.pk))
        self.client_a.logout()

        # Same username exists in Hospital B, but its password must not work
        # on Hospital A's subdomain — the two accounts are entirely distinct.
        self._login(self.client_a, "doctor1", "pass-b")
        self.assertNotIn("_auth_user_id", self.client_a.session)

    def test_cross_hospital_visit_is_404_not_403(self):
        self._login(self.client_a, "doctor1", "pass-a")

        # visit_b belongs to Hospital B. From Hospital A's subdomain it must
        # be invisible (404), not merely forbidden (403) — TenantManager
        # scopes the get_object_or_404 lookup itself, before the view's own
        # doctor-ownership check ever runs.
        response = self.client_a.get(reverse("visit_detail", args=[self.visit_b.pk]))

        self.assertEqual(response.status_code, 404)

    def test_patient_list_never_surfaces_another_hospitals_patients(self):
        self._login(self.client_a, "staff1", "pass-a")

        response = self.client_a.get(reverse("patient_list"))

        names = [p.full_name for p in response.context["patients"]]
        self.assertIn("Hospital A Patient", names)
        self.assertNotIn("Hospital B Patient", names)


class TenantHeaderFallbackTests(TestCase):
    """
    X-Hospital-Subdomain (hospital/middleware.py) exists only so mobile
    emulators/devices — which can't reach the dev machine via a real
    *.BASE_DOMAIN subdomain — can still pick a tenant locally. It's gated
    on settings.DEBUG specifically so it can never activate in a real
    deployment; these tests lock in both halves of that guarantee.
    """

    def setUp(self):
        self.hospital = Hospital.objects.create(name="Header Hospital", subdomain="headerh")
        # A bare host that doesn't match any subdomain of BASE_DOMAIN —
        # simulates an emulator hitting the dev machine's LAN IP directly.
        self.client_bare = Client(HTTP_HOST="127.0.0.1:8000")

    @override_settings(DEBUG=True)
    def test_header_resolves_tenant_when_debug_true(self):
        response = self.client_bare.get(
            reverse("login"), HTTP_X_HOSPITAL_SUBDOMAIN="headerh"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.hospital, self.hospital)

    @override_settings(DEBUG=False)
    def test_header_is_ignored_when_debug_false(self):
        response = self.client_bare.get(
            reverse("login"), HTTP_X_HOSPITAL_SUBDOMAIN="headerh"
        )

        # Host doesn't match a subdomain and the header must be completely
        # inert outside DEBUG — this is the platform (no-tenant) path, not
        # the header's hospital.
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.wsgi_request.hospital)
