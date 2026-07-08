# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Django 6.0 Hospital Management System (HMS). Single Django project (`HMS/`) with a single app (`hospital/`) that holds all models, views, and business logic. Postgres database. Server-rendered templates (no frontend build step, no JS framework — vanilla CSS/JS per page).

## Environment setup

- The Python virtualenv lives in `test/` at the repo root — **this is the venv, not a test suite**. Don't confuse it with `hospital/tests.py`.
  - Windows: `./test/Scripts/python.exe`, `./test/Scripts/pip.exe`
- Config is environment-variable based via `python-decouple`. Copy `.env.example` to `.env` and fill in real values (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`). `.env` is gitignored; never commit it.
- Install deps: `./test/Scripts/python.exe -m pip install -r requirements.txt`

## Common commands

Run all commands from the repo root (where `manage.py` lives).

```
# Dev server
./test/Scripts/python.exe manage.py runserver

# Run the full test suite (spins up a throwaway Postgres test DB automatically —
# the DB user needs CREATE DATABASE privilege)
./test/Scripts/python.exe manage.py test hospital

# Run one test class or one test
./test/Scripts/python.exe manage.py test hospital.tests.ReceptionWorkflowTests
./test/Scripts/python.exe manage.py test hospital.tests.ReceptionWorkflowTests.test_book_appointment_and_checkin_issues_queue_ticket

# Migrations (single app in this project)
./test/Scripts/python.exe manage.py makemigrations hospital
./test/Scripts/python.exe manage.py migrate

# System checks (fast sanity check, no DB required)
./test/Scripts/python.exe manage.py check

# One-off data/model exploration
./test/Scripts/python.exe manage.py shell -c "..."
```

## Architecture

### Roles and auth

`hospital.User` is a custom `AbstractUser` (`AUTH_USER_MODEL = 'hospital.User'`) with a `role` field (`ADMIN`, `DOCTOR`, `NURSE`, `RECEPTIONIST`, `LAB`, `PHARMACIST`, `CASHIER`, `PATIENT`, `STOCK_MANAGER`). Role gating for app views is done in application code, not Django's permission system:

- `hospital/decorators.py`: `@role_required("DOCTOR")` (wraps `login_required`) restricts a view to specific roles.
- `hospital/permissions.py`: object-level checks beyond role. `can_doctor_access(user, visit)` and `can_nurse_access(user, visit)` differ on purpose — a doctor must be the visit's *assigned* doctor (`visit.doctor_id == user.id`), while a nurse just needs the visit to be `WAITING_DOCTOR` (nurses/lab/pharmacy work a shared queue; only doctors have a real per-visit assignment via `Visit.doctor`). Don't loosen the doctor check without a reason — it was tightened deliberately after a cross-patient-access gap was found.
- `hospital/views.py`: `ROLE_REDIRECTS` maps each role to its dashboard URL name; `login_view`/`post_login_redirect` both funnel through `_redirect_for_role` so they can't drift apart.
- `hospital/signals.py` has two `post_save` receivers on `User`, both wired up via `hospital/apps.py`'s `ready()`:
  - `create_role_profile` auto-creates a `Doctor`/`Nurse` profile row, deferred via `transaction.on_commit` so a User row is never left without its profile if something later in the same transaction rolls back.
  - `grant_admin_staff_access` gives `ADMIN`-role users `is_staff` plus membership in a `Hospital Admins` Django `Group` (permissions defined once on the group — see `ADMIN_MANAGED_MODELS` in `signals.py` — not drifted per-user), so they can actually use the Django admin links on their dashboard. This one runs synchronously (no `on_commit`), which matters for testing — see below. It only ever grants access; a role change away from `ADMIN` doesn't revoke it. `AuditLog` deletion is deliberately excluded from the group and stays reserved for `is_superuser` (see `AuditLogAdmin.has_delete_permission`) — don't fold that into the group grant.

### The Visit state machine

`Visit.status` is the backbone that every clinical workflow reads and writes. It only moves forward:

```
REGISTERED → WAITING_DOCTOR → IN_CONSULTATION → {WAITING_LAB → WAITING_PHARMACY} → COMPLETED
```

`WAITING_LAB` and `WAITING_PHARMACY` are conditional branches, not both guaranteed — a visit may skip either or both. The routing decisions live in `hospital/services.py`, not scattered across views:

- `visit_status_after_consultation(visit)` — called when a doctor completes a consultation. Routes to `WAITING_LAB` if any lab test was ordered (checked first — lab takes precedence over pharmacy), else `WAITING_PHARMACY` if anything was prescribed, else `COMPLETED`.
- `visit_status_after_lab(visit)` — called when a lab order is fully resulted. Routes to `WAITING_PHARMACY` if a prescription exists, else `COMPLETED`. This is what lets a visit that needed *both* lab work and medication actually reach pharmacy after lab, instead of dead-ending.

Reception's check-in (`appointment_checkin`) is what creates the `Visit` in the first place (from a `SCHEDULED` `Appointment`), along with a `QueueTicket`.

### services.py vs views.py vs permissions.py

This split is intentional and worth keeping:
- **`services.py`** — domain/business logic with no HTTP awareness: state-machine routing (`visit_status_after_*`), stock dispensing (`dispense_prescription_item`, FEFO batch deduction), lab completion checks (`lab_order_fully_resulted`), service-gate checks. Pure functions taking model instances, safe to unit test without a request.
- **`permissions.py`** — "can this user do this to this object" predicates, reused by views to decide both access (403) and what UI to show.
- **`views.py`** — HTTP glue only: pull the request/form, call into services/permissions, redirect. Keep business logic out of here.

### The workflow module pattern

Each staff role's workflow (Reception, Doctor, Pharmacy, Lab, Cashier, Nurse, Stock Manager) follows the same shape — replicate it for new roles rather than inventing a new one:

1. **Dashboard view** — lists the role's queue (e.g. `Visit.objects.filter(status=Visit.Status.WAITING_LAB)`), role-gated with `@role_required`.
2. **Detail view** — one record (a `Visit`), re-checks status/ownership server-side even though the dashboard already filtered (defense in depth — someone can always type a URL directly).
3. **POST-only action sub-views** — one per mutation (start consultation, record vitals, dispense an item, record a lab result...), each re-validates state before writing and redirects back to the detail view (POST-redirect-GET; never render a page directly from a POST handler).
4. Actions with a real race window (queue ticket numbering, stock deduction, "is everything on this order done yet") wrap the critical section in `transaction.atomic()` with `select_for_update()` on the row being serialized. See `appointment_checkin`, `dispense_prescription_item`, `record_lab_result` for the pattern.
5. When a form is rendered multiple times on one page for different items (e.g. one "enter result" form per pending lab test), give each instance a distinct `prefix=str(item.pk)` — otherwise Django emits duplicate HTML `id`/`name` attributes across the forms.
6. When a POST handler rejects a form, use `_flash_form_errors(request, form, fallback)` (in `views.py`) to surface the actual field error(s) as messages rather than a generic "check the values entered" — the PRG redirect back to the detail page means the invalid form/its errors aren't re-rendered inline, so this is the only way the user finds out *why* it failed.

### Templates and static assets

- `templates/dashboards/*.html` — one template per dashboard/detail page, no shared base template/layout inheritance currently.
- `static/css/reception.css` — shared "light admin panel" theme used by Reception, Pharmacy, Lab, Cashier, Nurse, and Stock Manager pages (badges, cards, tables, forms). Reuse this for new admin-style staff pages rather than writing a new stylesheet.
- `static/css/doctor.css` — distinct purple-gradient theme, used only by the Doctor dashboard/consultation pages.
- `static/css/admin.css` — the Admin dashboard's own theme (KPI stat tiles, chart chrome), built against the dataviz skill's validated palette.
- `static/css/login.css` / `patient_dashboard.css` — patient-facing pages have their own richer styling (Lucide/Font Awesome icons via CDN).

### Admin dashboard charts

The Admin dashboard (`admin_dashboard` in `views.py`) renders hand-built inline SVG bar/line charts — no charting library. Geometry (bar/line pixel coordinates, rounded-corner SVG path strings) is computed in Python (`_build_bar_chart`, `_build_line_chart`, `_rounded_top_bar_path`, near the bottom of `views.py`) rather than in the template, because Django templates have no general arithmetic and hand-deriving pixel math in template tags is unreadable and easy to get subtly wrong. If you add another chart, reuse these helpers rather than writing new template-side math. Follow the project's `dataviz` skill for anything chart/color-related before changing this code.

### Testing conventions

`hospital/tests.py` has one `TestCase` class per workflow (`ReceptionWorkflowTests`, `DoctorWorkflowTests`, `PharmacyWorkflowTests`, `LabWorkflowTests`, `CashierWorkflowTests`, `NurseWorkflowTests`, `StockManagerWorkflowTests`, `AdminDashboardTests`, `AdminStaffAccessSignalTests`). Tests exercise views through `self.client` (POST/GET + assert redirects/DB state), not by calling service functions directly — this is what catches things like missing form fields or CSRF/permission wiring. Tests run against a real throwaway Postgres database created per run, not SQLite or mocks.

**Gotcha:** Django's `TestCase` wraps each test in a transaction it rolls back at the end, so `transaction.on_commit(...)` callbacks registered during the test **never fire** — e.g. `create_role_profile` in `signals.py` won't actually create a `Doctor`/`Nurse` profile row inside a `TestCase`. Tests that need one create it directly (`Doctor.objects.create(user=..., department=...)`) instead of relying on the signal. `grant_admin_staff_access` is deliberately *not* deferred via `on_commit` for exactly this reason, so it is directly testable with plain `TestCase`.

## Current workflow status

Built end-to-end (views + forms + templates + tests): **Reception** (register patient, book appointment, check in → queue ticket), **Doctor** (consult, vitals, diagnosis, prescribe, order labs, complete visit), **Pharmacy** (dispense prescriptions with FEFO stock deduction), **Lab** (record results, route visit onward), **Cashier** (bill a visit, collect payment against `VisitInvoice`/`Payment`), **Nurse** (pre-consultation vitals triage), **Stock Manager** (receive/write-off stock with transaction logging), **Admin** (hospital-wide KPI/trend/occupancy dashboard).

Still stubs (route exists, template renders, no real logic wired up): the telemedicine/records-download/prescription-refill patient-facing views. Nothing populates `AuditLog` yet — the admin dashboard links to it read-only, but no code writes entries to it.
