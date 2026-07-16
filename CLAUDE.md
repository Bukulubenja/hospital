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

## Security & CI

- `HMS/settings.py`'s TLS-related settings (`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_HSTS_SECONDS` + subdomains/preload) are env-driven via `python-decouple`, defaulting to off/0 so local HTTP dev keeps working unmodified. `.env.example` documents the production values and links to Django's HSTS docs — read those before flipping `SECURE_HSTS_SECONDS` on for real, a wrong value there is hard to undo (browsers cache it for the duration). `./test/Scripts/python.exe manage.py check --deploy` is the way to verify these before an actual deployment; it will legitimately warn on a fresh `.env` copy until the TLS vars above are set.
- `.github/workflows/ci.yml` runs on every push/PR to `main`: migrates against a Postgres service container, runs `check --deploy --fail-level WARNING` (with the TLS env vars forced on just for that step, so it validates the settings.py wiring without breaking the plain-HTTP test client used by the step after it), runs the full `hospital` test suite, and a separate job runs `pip-audit` against `requirements.txt`. If you add a new required production setting to `settings.py`, wire its "on" value into that same deploy-checklist step or CI will stop catching drift on it.
- `requirements.txt` pins are audited by CI on every push — if `pip-audit` flags a pin, check the release notes for a same-minor patch release before doing anything more invasive (this is how Django 6.0.6 → 6.0.7 happened, fixing three low-severity CVEs with a one-line version bump and no code changes).

## Architecture

### Roles and auth

`hospital.User` is a custom `AbstractUser` (`AUTH_USER_MODEL = 'hospital.User'`) with a `role` field (`ADMIN`, `DOCTOR`, `NURSE`, `RECEPTIONIST`, `LAB`, `PHARMACIST`, `CASHIER`, `PATIENT`, `STOCK_MANAGER`). Role gating for app views is done in application code, not Django's permission system:

- `hospital/decorators.py`: `@role_required("DOCTOR")` (wraps `login_required`) restricts a view to specific roles.
- `hospital/permissions.py`: object-level checks beyond role. `can_doctor_access(user, visit)` and `can_nurse_access(user, visit)` differ on purpose — a doctor must be the visit's *assigned* doctor (`visit.doctor_id == user.id`), while a nurse just needs the visit to be `WAITING_DOCTOR` (nurses/lab/pharmacy work a shared queue; only doctors have a real per-visit assignment via `Visit.doctor`). Don't loosen the doctor check without a reason — it was tightened deliberately after a cross-patient-access gap was found.
- Patient portal logins are a `User(role=PATIENT)` linked to an existing `Patient` row via `Patient.user` (`OneToOneField`, nullable). Reception still creates the `Patient` record as always; an ADMIN separately creates the login `User` in Django admin and links it via the `user` field on `Patient` (`autocomplete_fields` in `PatientAdmin`) — there's no self-service signup and no signal auto-creates this link (unlike Doctor/Nurse), since the `Patient` row already exists. `hospital/services.py`'s `patient_for_user(user)` resolves the link; every patient-facing view uses it and scopes queries to that `Patient` instead of a permissions predicate (there's no shared queue for patients to gate).
- `hospital/views.py`: `ROLE_REDIRECTS` maps each role to its dashboard URL name; `login_view`/`post_login_redirect` both funnel through `_redirect_for_role` so they can't drift apart.
- `settings.LOGIN_URL = "login"` (the app's own `login_view`, not Django's default `/accounts/login/`) — every `@role_required`/`@login_required` view redirects unauthenticated access here. This was missing for most of the project's life (only caught when testing the patient dashboard's logout link end-to-end): without it, hitting a protected page while logged out 404s at `/accounts/login/` instead of showing the real login form. `login_view` itself ignores `?next=` and always sends a successful login to `_redirect_for_role(user)` — that's intentional, not a bug to "fix" by wiring up `next`.
- Password reset uses Django's built-in `PasswordResetView`/`PasswordResetDoneView`/`PasswordResetConfirmView`/`PasswordResetCompleteView` (wired in `hospital/urls.py` under `/hospital/password-reset/...` and `/hospital/reset/<uidb64>/<token>/`, not `django.contrib.auth.urls` wholesale — that would collide with the custom `login`/`logout` names). Templates live at `templates/password_reset_*.html` (not under `dashboards/`, since this isn't role-gated) and reuse `login.css`'s `.glass`/`.input-group`/`.login-btn` classes for visual consistency with `login.html`. `EMAIL_BACKEND` defaults to the console backend (prints to stdout) via `.env`'s `EMAIL_*` vars — switch to the SMTP backend there to actually deliver reset emails; nothing in the code needs to change. "Remember Me" on login is real: checked sets `request.session.set_expiry(1209600)` (persists 2 weeks), unchecked sets `set_expiry(0)` (expires when the browser closes) — see `login_view`.
- `templates/dashboards/patient.html` was a duplicate, unreferenced copy of `patient_dashboard.html` (same broken-nav-tab bug, several dead `href="#"` links) — deleted. If a `dashboards/patient.html` reappears, it's not wired to any view; don't resurrect it as a real page without checking whether `patient_dashboard.html` already covers the need.
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

Telemedicine is **not** a separate state machine — an `Appointment`/`Visit` with `consultation_type=TELEMEDICINE` goes through exactly this same flow (check-in, doctor queue, consultation). The only difference is `Appointment.meeting_link`, an external video-call URL (no in-app video/chat is built); Reception sets it from `appointment_list`, the patient sees a "Join Call" link once it's set, and the doctor sees the same link on `visit_detail` via `visit.appointment.meeting_link`.

A prescription refill also reuses the pharmacy flow rather than inventing one: `RefillRequest` (patient, source `PrescriptionItem`, status) is created by the patient, and `approve_refill_request(refill_request, doctor)` in `services.py` clones the source item onto a **new** `Visit` that starts life already `WAITING_PHARMACY` — no new visit ever goes through a doctor consultation, since the doctor's approval *is* the consultation for a refill. This means `pharmacy_dashboard`/`prescription_detail`/`dispense_item` needed zero changes to support refills.

### Notifications, messaging, and emergency alerts

- `Notification` (`user`, `title`, `description`, `is_read`) is a generic per-user inbox item. `create_notification(user, title, description)` in `services.py` is a no-op if `user` is `None` (e.g. a `Patient` not yet linked to a login) — callers don't need to guard that themselves. Currently fired from `approve_refill_request`/`deny_refill_request` (services.py) and from the messaging views below. Only the patient dashboard renders a notification bell today; nothing stops other roles from reading their own `Notification` rows if a UI is added later.
- `Message` (`patient`, `doctor`, `sender`, `body`, `is_read`) models one (patient, doctor) conversation thread; `sender` disambiguates direction since both parties post into the same thread. A patient may only message a doctor who has an actual `Visit` with them (checked via `Visit.objects.filter(doctor=doctor, patient=patient).exists()`, not `get_object_or_404` with a joined filter — the latter risks `MultipleObjectsReturned` when a patient has more than one visit with the same doctor). `patient_messages`/`patient_message_thread` (patient side) and `doctor_messages`/`doctor_message_thread` (doctor side) both mark the *other* party's messages read on GET, and send a `Notification` to the recipient on POST.
- `EmergencyAlert` (`patient`, `severity`, `details`, optional `latitude`/`longitude`, `status`) is raised by the patient dashboard's emergency modal via a JSON POST to `emergency_alert_create` (browser geolocation is captured client-side in `patient_dashboard.js` only if the patient opts in — a denied/unavailable location never blocks sending the alert). Reception is the front-line role that sees and works these: `reception_dashboard` lists all non-`RESOLVED` alerts, and `emergency_alert_acknowledge`/`emergency_alert_resolve` progress them. There's no push/real-time layer in this stack, so an alert only appears once Reception's dashboard is (re)loaded — the modal's copy tells the patient to call emergency services directly for life-threatening cases rather than relying solely on this.
- `queue_snapshot_for_patient(patient)` in `services.py` replaced the old fabricated "Smart Queue Prediction" numbers with a real computation off today's unserved `QueueTicket` rows: queue number, position (count of unserved tickets at or before it), and a wait estimate using a flat `AVERAGE_CONSULTATION_MINUTES` constant — the only heuristic here, since there's no real per-consultation timing data to derive it from.
- `patient_dashboard.html`'s sidebar nav is single-page anchor navigation (`patient_dashboard.js` intercepts `a[href^="#"]` clicks and smooth-scrolls) — every `<a href="#x">` in the sidebar **must** have a matching `id="x"` on the section/card it's supposed to jump to, or the click silently does nothing. This broke for all 10 nav items at once (IDs didn't exist anywhere on the page) until each card got its matching `id`, and two nav items (`#profile`, `#settings`) pointed at sections that didn't exist at all — added a real read-only "My Profile" card (sourced from the existing `patient` context, no new view logic) and a real "Account Settings" card with a working change-password form (`patient_change_password` view, Django's built-in `PasswordChangeForm` + `update_session_auth_hash` so the session survives the change). If you add another sidebar nav item, add the matching `id` in the same edit — it's easy to add one without the other and end up with a dead link again.

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
- `static/css/login.css` / `patient_dashboard.css` — patient-facing pages have their own richer styling (Lucide/Font Awesome icons via CDN). `patient_dashboard.css`'s component classes (`.card`, `.prescription-item`, `.telemedicine-tile`, `.tile-grid`, `.summary-tile`, `.billing-table`, `.form-group`) are shared by every patient-facing page (dashboard, telemedicine, refills, records, lab results, invoices), not just the dashboard — reuse them rather than writing new patient-facing CSS.

### Responsive design

All five stylesheets (`reception.css`, `doctor.css`, `admin.css`, `login.css`, `patient_dashboard.css`) have real breakpoints now — verified with Playwright at 320/375/768/1440px on every dashboard, zero horizontal overflow. Two gotchas worth knowing if you touch layout CSS here again:

- **Flex/grid item `min-width: auto` default.** A flex or grid item won't shrink below its content's intrinsic width unless you set `min-width: 0` on it explicitly. This caused two separate real bugs this pass: `.main-content` (flex item of `.container-main`) and `.login-panel`/`.glass`/`.input-group input` (grid/flex items on the login page) were all silently forcing their ancestors wider than the viewport on phones, even though every *visible* rule looked fine — nothing was clipped or ugly in a screenshot, the page just gained horizontal scroll. If you add a new flex/grid item that wraps significant content (especially a `<input>`, which has a large built-in intrinsic minimum width), add `min-width: 0` to it up front.
- **Tables aren't given a scroll wrapper in markup** — instead every themed `.card` has `overflow-x: auto`, so a wide `<table>` (5+ columns is common in the reception/doctor/admin themes) scrolls horizontally within its own card instead of blowing out the page. Keep tables inside a `.card` (or add `overflow-x: auto` to whatever wraps them) rather than adding per-table wrapper markup.

The patient dashboard's sidebar is off-canvas below 1024px (`.sidebar.active`/`.sidebar-backdrop.active`, toggled by `#sidebar-toggle` in `patient_dashboard.js`) — this used to have no way to open it at all (the toggle button didn't exist), making the entire nav unreachable on phones and most tablets. If you touch the sidebar markup, keep `#sidebar`/`#sidebar-toggle`/`#sidebar-backdrop` ids in sync with the JS, and keep `.sidebar`'s off-canvas behavior consistent across the 1024px *and* 768px breakpoints (it used to fight itself — 768px forced the sidebar back to always-visible-inline, undoing the 1024px toggle logic).

### Admin dashboard charts

The Admin dashboard (`admin_dashboard` in `views.py`) renders hand-built inline SVG bar/line charts — no charting library. Geometry (bar/line pixel coordinates, rounded-corner SVG path strings) is computed in Python (`_build_bar_chart`, `_build_line_chart`, `_rounded_top_bar_path`, near the bottom of `views.py`) rather than in the template, because Django templates have no general arithmetic and hand-deriving pixel math in template tags is unreadable and easy to get subtly wrong. If you add another chart, reuse these helpers rather than writing new template-side math. Follow the project's `dataviz` skill for anything chart/color-related before changing this code.

### Testing conventions

`hospital/tests.py` has one `TestCase` class per workflow (`ReceptionWorkflowTests`, `DoctorWorkflowTests`, `PharmacyWorkflowTests`, `LabWorkflowTests`, `CashierWorkflowTests`, `NurseWorkflowTests`, `StockManagerWorkflowTests`, `AdminDashboardTests`, `AdminStaffAccessSignalTests`, `PatientWorkflowTests`). Tests exercise views through `self.client` (POST/GET + assert redirects/DB state), not by calling service functions directly — this is what catches things like missing form fields or CSRF/permission wiring. Tests run against a real throwaway Postgres database created per run, not SQLite or mocks.

**Gotcha:** a model field with a `default` (e.g. `Appointment.consultation_type`) still needs `blank=True` if any existing form that doesn't supply that field (e.g. Reception's `AppointmentForm` before telemedicine existed) should keep validating — `default` only applies at the DB/model level, not to `ModelForm` required-ness, which is driven by `blank`. Missing this broke `ReceptionWorkflowTests` when `consultation_type` was added; caught by running the full suite, not just the new tests.

**Gotcha:** Django's `TestCase` wraps each test in a transaction it rolls back at the end, so `transaction.on_commit(...)` callbacks registered during the test **never fire** — e.g. `create_role_profile` in `signals.py` won't actually create a `Doctor`/`Nurse` profile row inside a `TestCase`. Tests that need one create it directly (`Doctor.objects.create(user=..., department=...)`) instead of relying on the signal. `grant_admin_staff_access` is deliberately *not* deferred via `on_commit` for exactly this reason, so it is directly testable with plain `TestCase`.

## Current workflow status

Built end-to-end (views + forms + templates + tests): **Reception** (register patient, book appointment, check in → queue ticket, acknowledge/resolve patient emergency alerts), **Doctor** (consult, vitals, diagnosis, prescribe, order labs, complete visit, approve/deny prescription refill requests, secure messaging inbox with patients), **Pharmacy** (dispense prescriptions with FEFO stock deduction), **Lab** (record results, route visit onward), **Cashier** (bill a visit, collect payment against `VisitInvoice`/`Payment`), **Nurse** (pre-consultation vitals triage), **Stock Manager** (receive/write-off stock with transaction logging), **Admin** (hospital-wide KPI/trend/occupancy dashboard), **Patient** (dashboard with own appointments/vitals/lab results/prescriptions/billing, request/cancel appointments, request a telemedicine visit and join it once Reception sets a meeting link, request a prescription refill and track its approval, view/print a medical records summary, real notification inbox, secure messaging with any doctor who has treated them, and a one-tap emergency alert with optional geolocation that raises a real `EmergencyAlert` for Reception to work).

Nothing patient-facing is stubbed or fabricated-looking anymore — the dashboard's "Smart Queue Prediction" now computes a real position/wait from `QueueTicket` data instead of showing hardcoded numbers, and the Messages/Notifications/Emergency Alert cards are backed by real models (`Message`, `Notification`, `EmergencyAlert`) instead of empty placeholders. `AuditLog` is populated via `record_audit_log(user, action, instance, ip_address=None)` in `services.py`, called from `views.py` at domain-significant patient-data mutations (diagnosis recorded, prescription item dispensed, lab result recorded, payment recorded, refill request approved/denied, emergency alert acknowledged/resolved) — not a blanket per-field signal on every model, matching this project's preference for explicit call sites over generic instrumentation. If you add a new mutation that should be audited, follow the same pattern: call `record_audit_log` from the view right after the `.save()`, passing `_client_ip(request)` for the IP.
