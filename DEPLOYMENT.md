# Deploying HMS (Railway)

This walks through hosting the Django web app (and its `/api/` layer, used by the mobile app) on [Railway](https://railway.app). It's written so you run every command yourself with your own Railway account — nothing here requires giving anyone else access to your account or payment details. (This is also exactly how the current live deployment was set up.)

## What you get vs. what you don't (read this first)

Railway's free generated domain (`your-app.up.railway.app`) is a single hostname — it has **no wildcard subdomain support**. This app's multi-tenancy depends on each hospital living at `<subdomain>.BASE_DOMAIN` (see [CLAUDE.md § Multi-tenancy](./CLAUDE.md#multi-tenancy)), so on the free domain:

- The bare domain works, over real HTTPS (Railway terminates TLS automatically even on the free domain): you can reach `/admin/` as a platform-operator superuser and create `Hospital` rows.
- An actual hospital's dashboards (`stjohns.your-app.up.railway.app`) **will not resolve** — Railway only routes the exact domain it assigned you, not subdomains of it.

This is enough to prove the deployment works end-to-end and to use the platform admin. To actually reach a hospital's dashboards, add a real domain you own later (~$10-15/year from any registrar) and point a wildcard record at Railway — Railway's custom domains support `*.yourdomain.com`. That step is one paragraph at the bottom of this guide once you have a domain.

## 1. Install the CLI and log in

```bash
npm install -g @railway/cli
railway login
```

This opens a browser to authenticate — nothing is shared with me, it's your own Railway session. (If `railway` isn't found afterward, npm's global bin directory — `npm config get prefix` — isn't on your PATH; call the CLI by its full path, e.g. on Windows `"$(npm config get prefix)\railway.cmd"`, until you add it to PATH.)

## 2. Create the project and services

From the repo root:

```bash
railway init --name hms                 # creates the project, links this directory to it
railway add --database postgres         # adds a Postgres service
railway add --service web               # adds an empty service for the Django app
```

Railway's Postgres service exposes `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` as variables automatically — no code changes needed, since `HMS/settings.py` already reads `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`/`DB_NAME` via `python-decouple`. You just need to map them (next step).

## 3. Set environment variables

```bash
railway variable set "SECRET_KEY=<generated below>" --service web --skip-deploys
railway variable set "DEBUG=False" --service web --skip-deploys
railway variable set 'DB_NAME=${{Postgres.PGDATABASE}}' --service web --skip-deploys
railway variable set 'DB_USER=${{Postgres.PGUSER}}' --service web --skip-deploys
railway variable set 'DB_PASSWORD=${{Postgres.PGPASSWORD}}' --service web --skip-deploys
railway variable set 'DB_HOST=${{Postgres.PGHOST}}' --service web --skip-deploys
railway variable set 'DB_PORT=${{Postgres.PGPORT}}' --service web --skip-deploys
```

Generate a real `SECRET_KEY` (never reuse a `django-insecure-...` dev key):

```bash
./test/Scripts/python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

The `${{Postgres.PGDATABASE}}`-style syntax is Railway's variable reference — it lets the `web` service read the `Postgres` service's variables directly, so you never copy/paste a password. (If you named the Postgres service something other than `Postgres`, use that name instead — check with `railway status`.)

## 4. Reserve a domain, then set BASE_DOMAIN/ALLOWED_HOSTS

```bash
railway domain --service web
```

This prints something like `web-production-a1b2.up.railway.app` — you can do this before the first deploy. Now set:

```bash
railway variable set "BASE_DOMAIN=web-production-a1b2.up.railway.app" --service web --skip-deploys
railway variable set "ALLOWED_HOSTS=web-production-a1b2.up.railway.app" --service web --skip-deploys
```

(No leading dot on `ALLOWED_HOSTS` — there's no wildcard to match yet, see the note at the top.)

Also turn on the HTTPS-dependent security settings now — Railway's free domain already serves real TLS, so there's no need to wait for a custom domain for this part:

```bash
railway variable set "SECURE_SSL_REDIRECT=True" --service web --skip-deploys
railway variable set "SESSION_COOKIE_SECURE=True" --service web --skip-deploys
railway variable set "CSRF_COOKIE_SECURE=True" --service web --skip-deploys
```

(Leave `SECURE_HSTS_SECONDS` at its default `0` for now — see the warning in `.env.example` about HSTS being hard to undo once browsers cache it.)

## 5. Deploy

```bash
railway up --service web
```

`railway.json` in the repo root controls the build/deploy behavior:

```json
{
  "build": { "buildCommand": "pip install -r requirements.txt && python manage.py collectstatic --noinput" },
  "deploy": { "preDeployCommand": "python manage.py migrate" }
}
```

**Why `collectstatic` is a build command and not a pre-deploy command**: Railway's `preDeployCommand` runs in its own throwaway container before the real one starts — anything it writes to disk (like collected static files) doesn't carry over. `migrate` is fine there because its effects live in the database, not the filesystem. `collectstatic`'s output has to be baked into the image itself, so it belongs in `buildCommand`. (This was found live: the first deploy attempt ran `collectstatic` as a pre-deploy step, and the running app came up with an empty `staticfiles/` directory — CSS/favicon all 404'd.)

The `Procfile` (`web: gunicorn HMS.wsgi --bind 0.0.0.0:$PORT --log-file -`) starts the actual server — note it binds to Railway's dynamic `$PORT`, not a hardcoded port; Railway won't route traffic to the container otherwise.

## 6. The CSRF-behind-a-proxy gotcha (already fixed in this repo, explained here so you know why)

The first real login attempt against the live deployment failed with **"CSRF verification failed. Request aborted."** Root cause: Railway (like most PaaS hosts) terminates TLS at an edge proxy and forwards plain HTTP internally, adding an `X-Forwarded-Proto: https` header to say so. Django doesn't trust that header by default, so `request.is_secure()` reports `False` even though the browser genuinely used HTTPS — which makes Django's CSRF Origin check compare `http://yourapp...` against the browser's real `https://yourapp...` Origin header, a mismatch that gets rejected as a forged request.

`HMS/settings.py` now sets:

```python
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default=f'https://{BASE_DOMAIN},https://*.{BASE_DOMAIN}', cast=Csv())
```

Nothing to do here on a fresh deploy — this is just context for why it's there, in case you ever see the same error again after changing proxy/hosting setups.

## 7. Create your platform superuser

```bash
railway run --service web -- ./test/Scripts/python.exe manage.py createsuperuser
```

`railway run` executes the command **locally** but with the deployed service's environment variables injected, so it talks to the real production database. The superuser you create here has `hospital=None` — the platform operator who creates `Hospital` tenants (see CLAUDE.md). This has to be run interactively by you (it prompts for username/email/password) — it can't be scripted unattended without choosing a password on your behalf.

To reset a password later: `railway run --service web -- ./test/Scripts/python.exe manage.py changepassword <username>`.

## 8. Verify

Visit `https://<your-railway-domain>/admin/`, log in as the superuser you just created, and create your first `Hospital` + its `ADMIN` user — same flow as local dev (see the root [README](./README.md#1-web-app-django)).

## 9. Redeploying after future changes

```bash
railway up --service web
```

`collectstatic` and `migrate` both run automatically as part of every deploy (see `railway.json` above) — no separate manual step needed.

## 10. Once you have a real domain (later, optional)

1. Buy a domain from any registrar.
2. Railway dashboard → your web service → **Settings → Networking → Custom Domain** → enter `*.yourdomain.com`.
3. Railway gives you a CNAME record — add it at your registrar for the `*` host.
4. Update env vars: `BASE_DOMAIN=yourdomain.com`, `ALLOWED_HOSTS=.yourdomain.com,yourdomain.com`.
5. `railway up --service web` to redeploy with the new variables.

Every hospital you create is now reachable at `<subdomain>.yourdomain.com` for real, exactly as designed.

## 11. Building the staff desktop app and patient mobile app against this deployment

Neither client needs a code or config change to point at a real deployment — both ask for the server address at first launch (see [CLAUDE.md § Mobile/desktop clients](./CLAUDE.md#mobiledesktop-clients)). Just build them and enter your Railway domain when prompted:

```bash
cd desktop-app
npm run dist                 # produces dist/HMS Staff Setup <version>.exe and dist/HMS Staff <version>.exe

cd ../mobile-app/android
./gradlew.bat assembleRelease   # produces app/build/outputs/apk/release/app-release.apk
```

The release APK is signed with the React Native template's default debug keystore (fine for direct-install/sideload distribution, not for a Play Store submission — that needs your own release keystore).

## Known limitations of this deployment (not fixed here, by design — ask if you want them addressed)

- **Media uploads aren't persistent.** Railway's filesystem is ephemeral — anything written to `MEDIA_ROOT` is lost on the next deploy/restart. Nothing in the current feature set writes user-uploaded files there today, so this is a latent gap, not an active bug — worth an S3-compatible storage backend before any feature does start uploading files.
- **Email is console-only until you set SMTP vars.** Password reset emails currently just print to Railway's logs (`EMAIL_BACKEND` default) — see `.env.example`'s `EMAIL_*` section to wire up a real provider.
