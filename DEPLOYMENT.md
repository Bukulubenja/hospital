# Deploying HMS (Railway)

This walks through hosting the Django web app (and its `/api/` layer, used by the mobile app) on [Railway](https://railway.app). It's written so you run every command yourself with your own Railway account — nothing here requires giving anyone else access to your account or payment details.

## What you get vs. what you don't (read this first)

Railway's free generated domain (`your-app.up.railway.app`) is a single hostname — it has **no wildcard subdomain support**. This app's multi-tenancy depends on each hospital living at `<subdomain>.BASE_DOMAIN` (see [CLAUDE.md § Multi-tenancy](./CLAUDE.md#multi-tenancy)), so on the free domain:

- The bare domain works: you can reach `/admin/` as a platform-operator superuser and create `Hospital` rows.
- An actual hospital's dashboards (`stjohns.your-app.up.railway.app`) **will not resolve** — Railway only routes the exact domain it assigned you, not subdomains of it.

This is enough to prove the deployment works end-to-end and to use the platform admin. To actually reach a hospital's dashboards, add a real domain you own later (~$10-15/year from any registrar) and point a wildcard record at Railway — Railway's custom domains support `*.yourdomain.com`. That step is one paragraph at the bottom of this guide once you have a domain.

## 1. Install the CLI and log in

```bash
npm install -g @railway/cli
railway login
```

This opens a browser to authenticate — nothing is shared with me, it's your own Railway session.

## 2. Create the project and a Postgres database

From the repo root:

```bash
railway init          # creates a new Railway project, links this directory to it
railway add            # choose "Database" -> "PostgreSQL"
```

Railway's Postgres plugin exposes `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` as variables automatically — no code changes needed, since `HMS/settings.py` already reads `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`/`DB_NAME` via `python-decouple`. You just need to map them (next step).

## 3. Set environment variables

In the Railway dashboard, open your web service → **Variables**, and add:

```
SECRET_KEY=<run the command below to generate one>
DEBUG=False
DB_NAME=${{Postgres.PGDATABASE}}
DB_USER=${{Postgres.PGUSER}}
DB_PASSWORD=${{Postgres.PGPASSWORD}}
DB_HOST=${{Postgres.PGHOST}}
DB_PORT=${{Postgres.PGPORT}}
```

Generate a real `SECRET_KEY` (never reuse a `django-insecure-...` dev key):

```bash
./test/Scripts/python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

The `${{Postgres.PGDATABASE}}`-style syntax is Railway's variable reference — it lets your web service read the database service's variables directly, so you never copy/paste a password. Type it in the Variables tab; Railway resolves it at deploy time.

Leave `BASE_DOMAIN`/`ALLOWED_HOSTS` unset for now — set them **after** step 4 once you know your generated domain.

## 4. Deploy

```bash
railway up
```

This builds and deploys using the `Procfile` (`web: gunicorn HMS.wsgi --log-file -`) already in the repo. Once it's live, generate a public domain:

```bash
railway domain
```

This prints something like `hms-production-a1b2.up.railway.app`. Now go back to Variables and set:

```
BASE_DOMAIN=hms-production-a1b2.up.railway.app
ALLOWED_HOSTS=hms-production-a1b2.up.railway.app
```

(No leading dot on `ALLOWED_HOSTS` — there's no wildcard to match yet, see the note at the top.) Redeploy for the new variables to take effect:

```bash
railway up
```

## 5. Run migrations and create your platform superuser

```bash
railway run python manage.py migrate
railway run python manage.py createsuperuser
```

`railway run` executes the command inside an ephemeral container with the same environment variables as your deployed service, so it talks to the real production database. The superuser you create here has `hospital=None` — the platform operator who creates `Hospital` tenants (see CLAUDE.md).

Static files are handled automatically on every deploy — `whitenoise` (added to `MIDDLEWARE`/`STORAGES` in `HMS/settings.py`) serves collected static assets directly from the app process, and Railway's Nixpacks build runs `collectstatic` as part of the standard Django build plan. No separate CDN/static host needed.

## 6. Verify

Visit `https://<your-railway-domain>/admin/`, log in as the superuser you just created, and create your first `Hospital` + its `ADMIN` user — same flow as local dev (see the root [README](./README.md#1-web-app-django)).

## 7. Redeploying after future changes

```bash
railway up
railway run python manage.py migrate   # only if you added new migrations
```

## 8. Once you have a real domain (later, optional)

1. Buy a domain from any registrar.
2. Railway dashboard → your web service → **Settings → Networking → Custom Domain** → enter `*.yourdomain.com`.
3. Railway gives you a CNAME record — add it at your registrar for the `*` host.
4. Update env vars: `BASE_DOMAIN=yourdomain.com`, `ALLOWED_HOSTS=.yourdomain.com,yourdomain.com`.
5. Also flip the TLS settings on now that you have real HTTPS via Railway's automatic cert: `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True` (leave `SECURE_HSTS_SECONDS` at `0` until you're confident everything else works — see the warning in `.env.example` about HSTS being hard to undo).
6. `railway up` to redeploy with the new variables.

Every hospital you create is now reachable at `<subdomain>.yourdomain.com` for real, exactly as designed.

## Known limitations of this deployment (not fixed here, by design — ask if you want them addressed)

- **Media uploads aren't persistent.** Railway's filesystem is ephemeral — anything written to `MEDIA_ROOT` is lost on the next deploy/restart. Nothing in the current feature set writes user-uploaded files there today, so this is a latent gap, not an active bug — worth an S3-compatible storage backend before any feature does start uploading files.
- **Email is console-only until you set SMTP vars.** Password reset emails currently just print to Railway's logs (`EMAIL_BACKEND` default) — see `.env.example`'s `EMAIL_*` section to wire up a real provider.
- **No process for the desktop/mobile apps here.** This guide only covers the Django backend; `desktop-app/` and `mobile-app/` just need their "server address" pointed at whatever domain you land on (bare Railway domain for now, since subdomain routing doesn't apply until step 8).
