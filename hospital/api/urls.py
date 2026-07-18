from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("auth/login/", views.PatientTokenObtainPairView.as_view(), name="api_login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="api_refresh"),
    path("patient/dashboard/", views.dashboard, name="api_patient_dashboard"),
    path(
        "patient/appointments/<int:pk>/cancel/",
        views.appointment_cancel,
        name="api_patient_appointment_cancel",
    ),
    path("patient/notifications/", views.notifications_list, name="api_patient_notifications"),
    path(
        "patient/notifications/mark-all-read/",
        views.notifications_mark_all_read,
        name="api_patient_notifications_mark_all_read",
    ),
    path("patient/emergency-alert/", views.emergency_alert_create, name="api_patient_emergency_alert"),
    path("patient/change-password/", views.change_password, name="api_patient_change_password"),
    path("patient/messages/", views.messages_list, name="api_patient_messages"),
    path("patient/messages/<int:doctor_pk>/", views.message_thread, name="api_patient_message_thread"),
    path("patient/refills/", views.refills_list, name="api_patient_refills"),
    path("patient/refills/<int:item_pk>/request/", views.request_refill, name="api_patient_request_refill"),
    path("patient/telemedicine/", views.telemedicine, name="api_patient_telemedicine"),
    path(
        "patient/telemedicine/history/",
        views.telemedicine_history,
        name="api_patient_telemedicine_history",
    ),
    path("patient/records/", views.records, name="api_patient_records"),
    path("patient/lab-results/", views.lab_results_list, name="api_patient_lab_results"),
    path("patient/invoices/", views.invoices_list, name="api_patient_invoices"),
    path("departments/", views.departments_list, name="api_departments"),
]
