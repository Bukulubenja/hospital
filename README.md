# HMS — Hospital Management System

A multi-tenant hospital management platform: one deployment serves many independent hospital organizations, each fully data-isolated and reachable at its own subdomain. Built with Django, with three ways to use it — a server-rendered web app for staff, a desktop app for staff (Electron wrapper), and a native mobile app for patients (React Native).

> Looking for deep architecture notes, gotchas, and the reasoning behind non-obvious decisions? See **[CLAUDE.md](./CLAUDE.md)** — it's written for AI coding agents working in this repo, but it's the most detailed technical reference here and is equally useful for human contributors.

## What this is

HMS runs the day-to-day operations of a hospital end to end:

- **Reception** — register patients, book appointments, check in patients into a live queue, triage emergency alerts
- **Doctor** — consult, record vitals and diagnosis, prescribe medication, order lab tests, complete visits, review prescription refill requests, message patients
- **Pharmacy** — dispense prescriptions against real stock (FEFO — first-expiry-first-out — batch deduction)
- **Lab** — record test results, route the visit onward automatically
- **Cashier** — bill a visit and collect payment
- **Nurse** — pre-consultation vitals triage
- **Stock Manager** — receive and write off pharmacy stock with a full transaction log
- **Admin** — a hospital-wide KPI/trend/occupancy dashboard
- **Patient** — a full self-service portal: appointments, telemedicine requests, prescription refills, medical records, lab results, billing, secure messaging with treating doctors, notifications, and one-tap emergency alerts

Every workflow above is real — no placeholder data, no fabricated numbers. The `Visit` model is the backbone: it moves through a real state machine (`REGISTERED → WAITING_DOCTOR → IN_CONSULTATION → [WAITING_LAB] → [WAITING_PHARMACY] → COMPLETED`) as each role acts on it.

## Multi-tenancy

One hospital = one tenant. All tenants share a single Postgres database (not one database per hospital), isolated by a `hospital` foreign key that's enforced automatically at the model layer — application code (views, services, forms) doesn't need to remember to filter by tenant. Each hospital is reached at its own subdomain (`stjohns.yourdomain.com`, `mercy.yourdomain.com`, ...). New hospitals are provisioned by hand today (no self-service signup or billing yet) by a platform-operator superuser via Django admin on the bare domain.

See **[CLAUDE.md § Multi-tenancy](./CLAUDE.md#multi-tenancy)** for exactly how tenant isolation is implemented and enforced.

## The three clients

| Client | Tech | Who it's for | Where |
|---|---|---|---|
| Web app | Django, server-rendered templates | All staff roles + patients (browser) | `hospital/`, `templates/`, `static/` |
| Staff desktop app | Electron | Hospital staff who want an installed app | [`desktop-app/`](./desktop-app/) |
| Patient mobile app | React Native CLI | Patients, on iOS/Android | [`mobile-app/`](./mobile-app/) |

The desktop app is a thin native wrapper around the same web UI — no separate code to maintain. The mobile app talks to a dedicated JSON API (`hospital/api/`, Django REST Framework + JWT) that mirrors the web patient dashboard's functionality exactly, reusing the same business logic (`hospital/services.py`) as the web views.

## Architecture at a glance

```
HMS/                    Django project settings, root URLs
hospital/               The single Django app — all models, views, business logic
  models.py             Domain models (Patient, Visit, Prescription, ...) + Hospital (tenant)
  tenancy.py            Tenant-scoping contextvar, manager, and abstract base model
  middleware.py          Resolves the current hospital from the request subdomain
  views.py / forms.py    Web UI (server-rendered templates)
  services.py             Business logic shared by web views and the API
  permissions.py           Object-level access checks (e.g. "is this doctor assigned to this visit?")
  signals.py               Auto-provisioning (role profiles, admin group access)
  api/                    REST API for the patient mobile app (DRF + JWT)
  tests.py, api/tests.py   Full workflow + tenant-isolation + API test suites
templates/               Server-rendered HTML, one folder per role dashboard
static/                  Per-theme CSS/JS (reception, doctor, admin, patient, login)
desktop-app/             Electron wrapper for staff (produces a Windows .exe)
mobile-app/              React Native CLI app for patients
.github/workflows/       CI: tests, Django deploy checklist, dependency scanning
```

## Getting started

### Prerequisites

- Python 3.13+, a Postgres server
- Node.js 20+ (for `desktop-app/` and `mobile-app/`)
- Android Studio / SDK (only if building the mobile app for Android) or Xcode (iOS)

### 1. Web app (Django)

```bash
# from the repo root
./test/Scripts/python.exe -m pip install -r requirements.txt   # test/ is the venv, not a test suite
cp .env.example .env   # fill in SECRET_KEY, BASE_DOMAIN, DB_*, etc.
./test/Scripts/python.exe manage.py migrate
./test/Scripts/python.exe manage.py createsuperuser             # platform operator (hospital=None)
./test/Scripts/python.exe manage.py runserver
```

Visit the bare `BASE_DOMAIN` (no subdomain) and log into `/admin/` as your superuser to create your first `Hospital` and its admin user. From then on, that hospital is reachable at `<subdomain>.<BASE_DOMAIN>`.

Run the test suite:

```bash
./test/Scripts/python.exe manage.py test hospital
```

Full command reference, environment variables, and multi-tenant local-dev setup (subdomains via `lvh.me`) are in [CLAUDE.md](./CLAUDE.md).

### 2. Staff desktop app

```bash
cd desktop-app
npm install
npm start          # run in development
npm run dist        # build a Windows installer + portable .exe
```

See [desktop-app/README.md](./desktop-app/README.md).

### 3. Patient mobile app

```bash
cd mobile-app
npm install
npx react-native start          # Metro bundler
npx react-native run-android    # or run-ios
```

The app asks for a hospital server address and subdomain on first launch. For local development against a USB-connected Android device, use `adb reverse tcp:8000 tcp:8000` to tunnel the device's `localhost` to your dev machine instead of configuring LAN IPs. See [CLAUDE.md § Mobile/desktop clients](./CLAUDE.md#mobiledesktop-clients) for the Windows-specific Android build fixes already applied in this repo (NDK/CMake pins, New Architecture) — don't "clean these up" without reading why they're there first.

## Deployment

See **[DEPLOYMENT.md](./DEPLOYMENT.md)** for a step-by-step guide to hosting the web app (and `/api/`) on Railway, including the tradeoffs of deploying without a custom domain yet (subdomain-based multi-tenancy needs one — see that doc for why and how to add it later).

## Security & CI

- Production TLS settings (HSTS, secure cookies, SSL redirect) are environment-driven and off by default so local HTTP development isn't affected — see `.env.example`.
- `manage.py check --deploy` validates production readiness before any real deployment.
- GitHub Actions runs the full test suite, the Django deploy checklist, and a dependency vulnerability scan (`pip-audit`) on every push.
- Every domain-significant mutation (diagnosis recorded, prescription dispensed, payment taken, etc.) is written to a real audit log (`AuditLog`), not just modeled and left empty.

Details: [CLAUDE.md § Security & CI](./CLAUDE.md#security--ci).

## Contributing / working in this repo

If you're a human contributor, skim [CLAUDE.md](./CLAUDE.md) first — it documents the project's architectural conventions (the `services.py` / `views.py` / `permissions.py` split, the workflow-module pattern each staff role follows, testing conventions) and a number of real bugs that were found and fixed during development, which are worth knowing before you re-introduce them.
