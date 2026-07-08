from django.urls import path
from . import views

urlpatterns = [
    path("redirect/", views.post_login_redirect, name="post_login"),
    path("doctor/", views.doctor_dashboard, name="doctor_dashboard"),
    path("nurse/", views.nurse_dashboard, name="nurse_dashboard"),
    path("reception/", views.reception_dashboard, name="reception_dashboard"),
    path("lab/", views.lab_dashboard, name="lab_dashboard"),
    path("pharmacy/", views.pharmacy_dashboard, name="pharmacy_dashboard"),
    path("cashier/", views.cashier_dashboard, name="cashier_dashboard"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("patient/", views.patient_dashboard, name="patient_dashboard"),
    path("", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("patient/", views.patient_dashboard, name="patient_dashboard"),
    path("appointments/", views.appointment_list, name="appointment_list"),
    path("appointments_create/", views.appointment_create, name="appointment_create"),
    path("prescription_refill/", views.prescription_refill, name="prescription_refill"),
    path("telemedicine_start/", views.telemedicine_start, name="telemedicine_start"),
    path("records_download/", views.records_download, name="records_download"),
    path("lab_result_list/", views.lab_result_list, name="lab_result_list"),
    path("invoice_list/", views.invoice_list, name="invoice_list"),
    path("telemedicine_chat/", views.telemedicine_chat, name="telemedicine_chat"),
    path("telemedicine_history/", views.telemedicine_history, name="telemedicine_history")


]
