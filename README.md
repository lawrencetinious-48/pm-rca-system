# Preventative Maintenance RCA System

A Flask-based preventive maintenance and RCA platform with role-based dashboards, PM/RCA field submission, desk review workflows, messaging, consumable tracking, optional S3 uploads, and PostgreSQL as the production database standard.

## Stack

- Python 3.10+
- Flask, Flask-Login, Flask-SQLAlchemy, Flask-Migrate
- PostgreSQL with `psycopg`
- Optional S3 upload storage
- Optional file-change watchdog reporting via `advanced_watchdog_script.py`

## Repository Layout

- Keep generated files out of the repository root.
- Runtime outputs and probe artifacts belong under `artifacts/`.
- Source code belongs in `pm_app/`, `templates/`, `static/`, `scripts/`, `tests/`, and `docs/`.

## Environment

Create `.env` from `.env.example`:

```bash
copy .env.example .env
```

Required or important variables:

- `APP_ENV`: `development`, `staging`, or `production`
- `DATABASE_URL`: required in production; optional in development/staging
- `DEV_DATABASE_URL`: optional development override (defaults to SQLite)
- `SECRET_KEY`: required outside tests
- `SESSION_COOKIE_SECURE`: set to `1` behind HTTPS, `0` for local HTTP
- `REMEMBER_COOKIE_SECURE`: set to `1` behind HTTPS, `0` for local HTTP
- `PREFERRED_URL_SCHEME`: should be `https` behind TLS
- `PUBLIC_BASE_URL`: recommended for externally shared login links
- `LOG_LEVEL`: application log level
- `ENABLE_INLINE_AUTOMATIONS`: when `1`, holiday and SLA maintenance tasks can run in request flow; defaults to `0` in production
- `ACCESS_LOG_ENABLED`: when `1`, emits per-request latency logs and request IDs
- `REDIS_URL`: optional, enables distributed login throttling
- `MAX_LOGIN_ATTEMPTS`, `LOGIN_WINDOW_SECONDS`, `LOGIN_LOCKOUT_SECONDS`: login throttle tuning
- `ALERT_EMAIL_ADDRESS` / `ALERT_EMAIL_PASSWORD`: optional app error email alerts
- `WATCHER_EMAIL_FROM` / `WATCHER_EMAIL_PASSWORD` / `WATCHER_EMAIL_TO`: optional watchdog reporting email settings

Database URL examples:

- Local PostgreSQL: `postgresql+psycopg://postgres:password@localhost:5432/pm_db`
- Managed PostgreSQL: `postgresql+psycopg://username:password@hostname:5432/database_name`
- Local SQLite (dev): `sqlite:///instance/dev_pm.sqlite`

## Database Modes

The application supports a dual-mode workflow:

- Development/staging (`APP_ENV=development` or `staging`):
	- Uses `DATABASE_URL` when provided
	- Falls back to SQLite automatically when `DATABASE_URL` is not set
- Production (`APP_ENV=production`):
	- Requires `DATABASE_URL`
	- Enforces PostgreSQL with psycopg (`postgresql+psycopg://...`)

This allows fast local development with SQLite while keeping production strict and predictable.

## Local Development

1. Create and activate a virtual environment.

```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Set up PostgreSQL and update `.env`.

4. Run migrations if you are managing schema changes through Flask-Migrate.

```bash
flask db upgrade
```

5. Start the app.

```bash
python app.py
```

Alternative local run:

```bash
flask --app app.py run --host 0.0.0.0 --port 5001
```

6. Open `http://127.0.0.1:5001/login/`.

If you do not set `DATABASE_URL` in development, the app will use SQLite automatically.

## Bootstrap Registration

- The first user can be created via `/register/` and is forced to the developer role (admin user).
- After the first account exists, `/register/` is locked down to authenticated admin users only.
- Admins create additional staff, technician, manager, and general manager accounts from the account management UI.

## Testing

The smoke suite lives under `tests/` and uses a temporary SQLite database only when `TESTING=True`. Production and normal development still require PostgreSQL.

Run tests with:

```bash
pytest
```

Current smoke coverage includes:

- anonymous redirect for protected dashboard access
- first-user registration bootstrap behavior
- registration lock-down after bootstrap
- CSRF-aware developer login
- authenticated consumable API create flow using server-side identity

## Quick Validation

Syntax check:

```bash
python -m compileall -q .
```

List routes:

```bash
flask --app app.py routes
```

Run maintenance tasks outside the request cycle:

```bash
flask --app app.py run-maintenance
```

## Docker Deployment

This repository now includes a `Dockerfile`, `.dockerignore`, and `docker-compose.yml`.

Start the stack:

```bash
docker compose up --build
```

Services:

- Web app: `http://localhost:5001`
- PostgreSQL: `localhost:5432`

Compose notes:

- The app container runs with `gunicorn --factory app:create_app`
- Compose overrides `DATABASE_URL` to point at the `db` service
- Uploaded files are persisted through the `./uploads` bind mount
- PostgreSQL data is persisted in the `postgres-data` volume

### Production-Like HTTPS (Recommended Path)

This project includes an HTTPS overlay using Caddy as a reverse proxy in front of Gunicorn.

Files:

- `Caddyfile`
- `docker-compose.https.yml`

What this gives you:

- TLS termination at the edge (port 443)
- HTTP -> HTTPS redirection
- `SESSION_COOKIE_SECURE=1` for secure cookies
- App still runs behind Gunicorn (`web:8000`) internally and is not exposed directly

1. Set your host name or LAN IP in `.env`:

```bash
set SERVER_NAME=localhost
```

For LAN testing from other devices, use your host IP instead:

```bash
set SERVER_NAME=172.16.0.62
```

2. Start the base stack plus HTTPS overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up --build -d
```

3. Open the app over HTTPS:

```text
https://localhost
```

or

```text
https://172.16.0.62
```

4. Stop the HTTPS stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml down
```

Notes:

- Caddy is configured with internal certificates (`tls internal`), which is ideal for production-like local/LAN testing.
- Browsers may warn until the local CA is trusted on each client device.
- In true public production, switch to a real domain and publicly trusted certificates.

## Watchdog Reporting

Use only `advanced_watchdog_script.py` for file-change reporting.

The older watchdog variants were removed because they contained unsafe embedded credentials. Configure reporting through environment variables instead:

- `WATCHER_EMAIL_FROM`
- `WATCHER_EMAIL_PASSWORD`
- `WATCHER_EMAIL_TO`

Run the watcher manually if needed:

```bash
python advanced_watchdog_script.py
```

## Storage and Uploads

- Local uploads are stored under `uploads/`
- Upload size limit is 16 MB
- Allowed file extensions are image types configured in the app
- If `S3_BUCKET` is set, the app can upload files to S3

## Main Routes

- `/login/`
- `/dashboard/`
- `/field/site-form/`
- `/desk/activities/`
- `/consumables/`
- `/notifications/`
- `/settings/`
- `/desk/approved-forms/excel`

## REST API

- `GET /api/dashboard-counts`
- `GET /api/consumables/`
- `GET /api/consumables/<id>/`
- `POST /api/consumables/`
- `GET /api/activities/`

Notes:

- API routes require authentication
- Mutating requests are CSRF-protected
- Consumable creation uses the authenticated user identity on the server side

## Production Notes

- Set a strong `SECRET_KEY`
- Set `APP_ENV=production`
- Set `SESSION_COOKIE_SECURE=1` behind HTTPS
- Point `PUBLIC_BASE_URL` at the public domain used for login links
- Set `REDIS_URL` in multi-instance deployments so login throttling is shared across workers
- Prefer `ENABLE_INLINE_AUTOMATIONS=0` in production and execute `flask --app app.py run-maintenance` from a scheduler
- Set `ACCESS_LOG_ENABLED=1` to emit request IDs and latency logs for incident investigation
- Rotate any credentials that were previously committed before deploying
- Prefer structured logging and external monitoring for production incidents
- Use PostgreSQL backups such as `pg_dump` / `pg_restore` for disaster recovery

## Migration Path: SQLite to PostgreSQL

Use this flow when development is complete:

1. Set production-style environment values:

```bash
set APP_ENV=production
set DATABASE_URL=postgresql+psycopg://username:password@hostname:5432/pm_db
```

2. Run schema migrations:

```bash
flask db upgrade
```

3. Run smoke tests against the app and key routes.

4. Keep SQLite for local feature work, but validate PostgreSQL before every release.

## Backup and Restore

Backup:

```bash
pg_dump --format=custom --file=pm_backup.dump postgresql://postgres:password@localhost:5432/pm_db
```

Restore:

```bash
pg_restore --clean --if-exists --no-owner --dbname=postgresql://postgres:password@localhost:5432/pm_db pm_backup.dump
```
#   p m - r c a - s y s t e m  
 #   p m - r c a - s y s t e m  
 #   p m - r c a - s y s t e m  
 