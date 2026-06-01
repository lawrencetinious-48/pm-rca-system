# Production Readiness Assessment & Operational Guide

## System Status: **CONFIGURATION-PENDING** ⚠️

This document answers critical deployment and operational questions, but the current status is **not yet production-ready** until a real production configuration and runtime environment are in place.

---

## 1. Is the System Up to Standards?

**The codebase is ready for production hardening, but deployment is still gated by configuration and infrastructure.** The system now enforces critical production checks for:
- ✅ Security: CSRF protection, HTTPS enforcement, secure cookies, password hashing (pbkdf2:sha256:150000)
- ✅ Database: PostgreSQL + psycopg (production enforced), connection pooling, automatic migrations
- ✅ Monitoring: Watchdog + Observability services for health checks and alerting
- ✅ Resilience: Redis fallback for login throttling, inline maintenance with cooldown windows
- ✅ Testing: Full pytest suite (74 tests pass, 0 failures), SQLAlchemy 2.0 compatibility
- ✅ Code Quality: No LegacyAPIWarning deprecations, PEP8-compliant, proper logging

**Production Enforcement Checks:**
- Raises `RuntimeError` if SECRET_KEY < 32 bytes or contains weak patterns
- Raises `RuntimeError` if SESSION_COOKIE_SECURE != 1 in production
- Raises `RuntimeError` if DATABASE_URL is not PostgreSQL with psycopg
- Raises `RuntimeError` if `PUBLIC_BASE_URL` is missing, non-HTTPS, localhost, or a placeholder
- Enforces HTTPS scheme when secure cookies enabled

**Current readiness blockers:**
- A real public `PUBLIC_BASE_URL` must be configured for production boot
- PostgreSQL, Redis, SMTP, and the monitoring stack must be reachable in the target environment
- Docker/Compose infrastructure must be deployed before the app can be considered live

---

## 2. One-Time Admin Account Creation

### Initial Deployment Flow

When the system is first deployed **with an empty database**:

1. **Bootstrap State Check** (`BootstrapState` model):
   - App checks if `bootstrap_state.bootstrap_complete = false`
   - If true, self-service admin registration endpoint `/register-developer` is exposed
   - If false, normal login page shown

2. **First Admin Registration**:
   - Navigate to `/register-developer` (or login attempts auto-redirect here)
   - **Single-use endpoint**: Creates exactly ONE admin account
   - After creation, the endpoint is disabled (sets `bootstrap_complete = true`)
   - Only works if `SELF_SERVICE_ENABLED=true` (default in staging/development, **disabled in production by default**)

3. **Production Deployment (Recommended)**:
   - Set `SELF_SERVICE_ENABLED=false` in `.env.prod` (default)
   - Create the first admin account **before** deploying:
     ```bash
     # In a local test environment
     SEED_SAMPLE_DATA=false python
     >>> from app import create_app
     >>> from model import User, db
     >>> app = create_app()
     >>> with app.app_context():
     ...     dev = User(email="admin@example.com", full_name="Admin", role="developer",
     ...                password_hash=<bcrypt-hash>)
     ...     db.session.add(dev)
     ...     db.session.commit()
     ```
   - **Or** temporarily set `SELF_SERVICE_ENABLED=true` in `.env.prod`, then disable after first account created.

### Bootstrap Table Schema
```sql
CREATE TABLE bootstrap_state (
    id INTEGER PRIMARY KEY,
    bootstrap_complete BOOLEAN NOT NULL DEFAULT FALSE,
    first_developer_id INTEGER REFERENCES "user"(id),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

## 3. Developer Login & User Creation Flow

### Login Process

**Developer Login:**
1. Navigate to `/login` → Select role="developer"
2. Enter email + password + CSRF token
3. Login throttling enforced:
   - Max 5 attempts per 15-minute window per IP+email
   - Redis-backed if available; falls back to in-memory store
   - 15-minute account lockout after threshold
4. On success:
   - Session created with 8-hour TTL
   - User settings (theme, language) loaded from database
   - Redirected to `/dashboard/`

**Multi-Role Support:**
- Developers can change account type at login (e.g., "developer" → "staff" for testing)
- Non-developers must use their assigned role

### Creating Other Users (Developer Admin Panel)

Once logged in as developer:
1. Navigate to **Admin > Users > Add Staff/Technician/Manager**
2. Fill form: email, name, role, gender, optional UID
3. System generates:
   - Initial password (emailed to user)
   - Account activation token (24-hour expiration)
   - User settings record (theme="light", language="en")
4. New user logs in with temporary password, forced to set permanent password

### Bulk Import (if needed)
- Admin can import users via CSV (Admin > Import Users panel)
- Generates activation emails for all

---

## 4. Watchdog Service (Health Monitoring)

### Purpose
Continuous background monitoring of system health. Runs as a separate daemon or Docker service.

### Watchdog Checks
| Check | Default Threshold | Action |
|-------|-------------------|--------|
| Database connectivity | N/A | Alert on failure |
| Redis availability | N/A | Alert on failure (optional) |
| Disk usage | >90% | WARNING email |
| Memory usage | >90% | WARNING email |
| CPU usage | >90% | WARNING email |
| Response time (app health endpoint) | >2s | WARNING email |
| Error rate from logs | >5% | WARNING email |

### Configuration (Environment Variables)
```bash
WATCHDOG_INTERVAL=300                          # Check every 5 minutes
WATCHDOG_RESPONSE_TIME_THRESHOLD=2.0           # seconds
WATCHDOG_CPU_THRESHOLD=90.0                    # percent
WATCHDOG_MEMORY_THRESHOLD=90.0                 # percent
WATCHDOG_DISK_THRESHOLD=90.0                   # percent
WATCHDOG_ERROR_RATE_THRESHOLD=0.05             # 5%
APP_URL=https://pm.example.com                 # Health check endpoint
REPORT_EMAIL=ops@example.com                   # Alert recipient
```

### Running Watchdog
```bash
# As a service in docker-compose.prod.yml (recommended)
docker-compose -f docker-compose.prod.yml up -d

# Or manually
python pm_app/services/watchdog.py &
```

### Alert Output
- Emails sent to `ALERT_EMAIL_ADDRESS` with SMTP credentials
- Logs written to `logs/watchdog.log`
- Alert cooldown: 30 minutes between same type of alerts (prevents spam)

---

## 5. Observability Service

### Request Tracking
- Every request assigned a UUID (`X-Request-ID`)
- Preserved across headers for end-to-end tracing
- Useful for debugging distributed issues

### Access Logging (Optional)
- Enabled by default in **staging/production**
- Disabled by default in **development**
- Logs format: `request_id=<uuid> method=GET path=/dashboard status=200 duration_ms=145`
- Controlled by:
  ```bash
  ACCESS_LOG_ENABLED=true  # In production
  ```

### Performance Monitoring
- Slow requests trigger alert if duration > `SLOW_REQUEST_ALERT_MS` (default 5s)
- 5xx errors trigger immediate alert
- All tracked in application logs

---

## 6. Database Strategy for Production

### Connection Pooling
**PostgreSQL (Production):**
```python
# In pm_app/legacy_app.py
SQLALCHEMY_ENGINE_OPTIONS = {
    "poolclass": QueuePool,
    "pool_size": 20,           # Max 20 idle connections
    "max_overflow": 30,        # Allow 30 overflow connections
    "pool_pre_ping": True,     # Test connection on checkout
    "pool_recycle": 3600,      # Recycle connections after 1 hour
    "pool_timeout": 30,        # Wait 30s for connection
    "echo": False              # Set True to log SQL (dev only)
}
```

### Migrations
- Alembic migrations in `migrations/versions/`
- Run automatically at startup if not applied
- Manual trigger:
  ```bash
  flask db upgrade
  ```

### Backup Strategy
- PostgreSQL should be backed up **daily** (at minimum)
- Use `pg_dump` or managed service backups
- Store encrypted backups off-site

### Database Initialization (Fresh Deploy)
1. Create PostgreSQL database:
   ```sql
   CREATE DATABASE pm_db OWNER pm_user;
   ```
2. Apply migrations:
   ```bash
   docker-compose -f docker-compose.prod.yml run app flask db upgrade
   ```
3. (Optional) Create first admin account as described in section 2

---

## 7. Test Form Data: Should the System Start Empty?

### **YES** — **Start with empty database in production**

Configuration:
```bash
# In .env.prod
SEED_SAMPLE_DATA=false       # Default in non-testing environments
APP_ENV=production
```

### What This Means
- No demo activities, consumables, or sample data seeded
- Clean slate for real operational data
- All data created by actual users (developers, technicians, managers, etc.)

### If You Want Sample Data (Staging/Demo)
- Set `SEED_SAMPLE_DATA=true` in staging `.env`
- System auto-populates sample sites, consumables, and demo activities on first run
- Used for training and testing workflows before production use

### Test Form Cleanup
- Test data created during testing stays in database unless manually deleted
- Recommended practice:
  - Use separate **test database** for QA
  - Run `pytest` against test DB (auto-seeded, auto-dropped after tests)
  - Keep production DB pristine

---

## 8. Maintenance & Automatic Cleanup

### Inline Maintenance Service
Runs **automatically during HTTP requests** (no separate service needed):
- Scans for SLA due-soon items → sends desk manager alerts
- Scans for SLA overdue items → escalates to development team
- Creates daily holiday greeting messages
- Respects cooldown windows to avoid alert spam

**Configuration:**
```bash
ENABLE_INLINE_AUTOMATIONS=false    # Disable in production if using Celery worker
INLINE_MAINTENANCE_MIN_INTERVAL_SECONDS=30
SLA_ESCALATION_ENABLED=true
```

### Celery Background Tasks (Optional)
If you deploy a `worker` service:
```bash
# docker-compose.prod.yml includes a worker service
docker-compose -f docker-compose.prod.yml up -d worker
```

Tasks:
- `send_async_email()` — Async email sending
- `generate_pdf_report()` — PDF generation
- `cleanup_old_files()` — Remove old uploads/logs (30+ days)
- `daily_health_report()` — Send daily metrics to admins
- `check_sla_deadlines()` — Periodic SLA scanning

---

## 9. Production Deployment Checklist

### Pre-Deployment
- [ ] Generate `SECRET_KEY` (32+ bytes): `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Configure PostgreSQL: `postgresql+psycopg://pm_user:password@host:5432/pm_db`
- [ ] Set `POSTGRES_PASSWORD` in `.env.prod`
- [ ] Set `REDIS_URL` (optional, for login throttling)
- [ ] Set `SESSION_COOKIE_SECURE=1` and `PREFERRED_URL_SCHEME=https`
- [ ] Configure email (SMTP): `ALERT_EMAIL_ADDRESS`, `ALERT_EMAIL_PASSWORD`
- [ ] Set `PUBLIC_BASE_URL` to production domain
- [ ] Disable self-service: `SELF_SERVICE_ENABLED=false`

### Deployment
```bash
# Build Docker image
docker build -t pm-app:prod .

# Start services
docker-compose -f docker-compose.prod.yml up -d --build

# Apply migrations
docker-compose -f docker-compose.prod.yml run app flask db upgrade

# (Optional) Create first admin account
docker-compose -f docker-compose.prod.yml run app python -c "..."
```

### Post-Deployment
- [ ] Verify `/health` endpoint responds 200
- [ ] Test login flow with admin account
- [ ] Confirm email alerts are sent to `ALERT_EMAIL_ADDRESS`
- [ ] Verify Watchdog logs appear in `logs/watchdog.log`
- [ ] Check that HTTPS redirects work (via Caddy)
- [ ] Run smoke test: create activity, approve, generate PDF

---

## 10. System Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                   Production Environment                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Caddy (TLS Termination) → Gunicorn (2 workers, 4 threads)  │
│         ↓                          ↓                         │
│       HTTPS              Flask App (pm-app:prod)           │
│                          - Auth routes                       │
│                          - Dashboard routes                  │
│                          - API routes                        │
│                          - Admin routes                      │
│                          - Watchdog (inline)                 │
│                          - Maintenance (inline)              │
│                                ↓                             │
│                     PostgreSQL Database                      │
│                    (connection pool: 20-50)                  │
│                                                              │
│                     Redis (optional)                         │
│                   (login throttling, cache)                  │
│                                                              │
│         Celery Worker (separate pod/container)             │
│         - Email sending                                      │
│         - PDF generation                                     │
│         - SLA escalation tasks                               │
│                                                              │
│         Watchdog Daemon (separate service)                  │
│         - Health checks every 5 minutes                      │
│         - Alert emails on threshold breach                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 11. Key Files & Locations

| Purpose | File | Notes |
|---------|------|-------|
| Bootstrap logic | `pm_app/auth/routes.py` L178-191 | One-time dev account creation |
| Developer login | `pm_app/auth/routes.py` L48-100 | Login throttling, role support |
| Watchdog service | `pm_app/services/watchdog.py` | Health monitoring daemon |
| Observability | `pm_app/services/observability.py` | Request tracking, logging |
| Maintenance | `pm_app/services/maintenance.py` | SLA alerts, escalations |
| Configuration | `pm_app/legacy_app.py` L101-400 | All app config logic |
| Database models | `model.py` | User, Activity, BootstrapState, etc. |
| Production config | `docker-compose.prod.yml` | Docker deployment |

---

## Conclusion

**The system is not yet production-ready until the environment is configured and the required services are running.** The codebase now enforces the critical production guardrails, but deployment should be treated as blocked until all of the following are true:
- ✅ Real `PUBLIC_BASE_URL` is configured and points to a public HTTPS host
- ✅ PostgreSQL is reachable and `DATABASE_URL` uses `postgresql+psycopg://`
- ✅ Redis is available if you want login throttling and cache-backed behavior
- ✅ SMTP is reachable for alert delivery
- ✅ Docker/Compose or the equivalent runtime stack is deployed

**Next Steps:**
1. Replace placeholder values in `.env.prod` with real production settings
2. Verify `PUBLIC_BASE_URL` is a real public HTTPS hostname
3. Bring up PostgreSQL, Redis, SMTP, and the monitoring stack
4. Deploy with `docker-compose.prod.yml`
5. Run the production health/ping checks
6. Create the first admin account
7. Enable Watchdog and Celery worker services
8. Monitor logs for the first 24 hours
