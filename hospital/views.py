from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .decorators import role_required

# Single source of truth for where each role lands after login.
# Reused by both login_view and post_login_redirect so they can never
# drift out of sync with each other.
ROLE_REDIRECTS = {
    "DOCTOR": "doctor_dashboard",
    "NURSE": "nurse_dashboard",
    "RECEPTIONIST": "reception_dashboard",
    "LAB": "lab_dashboard",
    "PHARMACIST": "pharmacy_dashboard",
    "CASHIER": "cashier_dashboard",
    "ADMIN": "admin_dashboard",
    "PATIENT": "patient_dashboard",
    "STOCK_MANAGER": "stock_dashboard",
}

DEFAULT_REDIRECT = "login"


def _redirect_for_role(user):
    """Resolve the correct dashboard URL name for a given user's role."""
    role = getattr(user, "role", None)
    return redirect(ROLE_REDIRECTS.get(role, DEFAULT_REDIRECT))


def login_view(request):
    if request.user.is_authenticated:
        return _redirect_for_role(request.user)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:
            messages.error(request, "Please enter both username and password.")
            return render(request, "login.html")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return _redirect_for_role(user)

        messages.error(request, "Invalid login details")

    return render(request, "login.html")


def post_login_redirect(request):
    if not request.user.is_authenticated:
        return redirect(DEFAULT_REDIRECT)

    return _redirect_for_role(request.user)


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect(DEFAULT_REDIRECT)


# ---------------------------------------------------------------------
# Role dashboards
# ---------------------------------------------------------------------
# All dashboards follow the same pattern (require login + a specific
# role, then render that role's template), so they're generated from
# one factory instead of eight near-identical function bodies.

def _make_dashboard_view(role, template_name):
    @login_required
    @role_required(role)
    def dashboard_view(request):
        return render(request, template_name)

    dashboard_view.__name__ = f"{role.lower()}_dashboard"
    return dashboard_view


doctor_dashboard = _make_dashboard_view("DOCTOR", "dashboards/doctor_dashboard.html")
nurse_dashboard = _make_dashboard_view("NURSE", "dashboards/nurse_dashboard.html")
reception_dashboard = _make_dashboard_view("RECEPTIONIST", "dashboards/reception.html")
lab_dashboard = _make_dashboard_view("LAB", "dashboards/lab.html")
pharmacy_dashboard = _make_dashboard_view("PHARMACIST", "dashboards/pharmacy.html")
cashier_dashboard = _make_dashboard_view("CASHIER", "dashboards/cashier.html")
admin_dashboard = _make_dashboard_view("ADMIN", "dashboards/admin.html")
patient_dashboard = _make_dashboard_view("PATIENT", "dashboards/patient_dashboard.html")
stock_dashboard = _make_dashboard_view("STOCK_MANAGER", "dashboards/stock.html")
appointment_list = _make_dashboard_view("RECEPTIONIST", "dashboards/appointment_list.html")
appointment_create = _make_dashboard_view("RECEPTIONIST", "dashboards/appointment_create.html")
prescription_refill = _make_dashboard_view("PHARMACIST", "dashboards/prescription_refill.html")
telemedicine_start = _make_dashboard_view("DOCTOR", "dashboards/telemedicine_start.html")
telemedicine_chat = _make_dashboard_view("DOCTOR", "dashboards/telemedicine_chat.html")
telemedicine_history = _make_dashboard_view("DOCTOR", "dashboards/telemedicine_history.html")
records_download = _make_dashboard_view("ADMIN", "dashboards/records_download.html")
lab_result_list = _make_dashboard_view("LAB", "dashboards/lab_result_list.html")
invoice_list = _make_dashboard_view("CASHIER", "dashboards/invoice_list.html")