# PM/RCA System - Enterprise Edition

> A production-ready Preventative Maintenance & Root Cause Analysis system with enterprise monitoring, self-service onboarding, and scalable architecture.

![Status](https://img.shields.io/badge/status-production%20ready-brightgreen)
![Monitoring](https://img.shields.io/badge/monitoring-Prometheus%2FGrafana-orange)
![Scalability](https://img.shields.io/badge/scale-horizontal-blue)

## Features

### Core Functionality
- **PM Forms** - Preventive Maintenance checklists with photo evidence
- **RCA Reports** - Root Cause analysis with SMART insights
- **Snag Tracking** - Issue tracking and resolution
- **Role-Based Access** - Developer, Manager, Staff, Technician roles
- **Photo Library** - Centralized image management with validation
- **Notifications** - Real-time alerts and messaging
- **Analytics Dashboard** - Real-time metrics and KPIs

### Enterprise Monitoring & Observability

Built-in production-grade monitoring stack:

- **Health Monitoring** - `/health` endpoint with comprehensive checks
- **Prometheus Metrics** - `/metrics` endpoint with 15+ custom metrics
- **Watchdog Service** - Continuous monitoring with email alerts
- **Daily Reporter** - Automated daily performance reports
- **Audit Logging** - Complete security event trail
- **Structured Logging** - JSON logs for log aggregation

### Self-Service Onboarding

For customers who purchase the system:

- **One-Click Developer Setup** - Create primary admin account instantly
- **Locked After First** - Only ONE developer allowed (security)
- **Email Confirmation** - Automatic welcome email with login URL
- **No Manual Intervention** - Fully automated provisioning

### High Performance & Scalability

- **Async Task Processing** - Celery + Redis for background jobs
- **Database Connection Pooling** - Optimized PostgreSQL connections
- **Multi-Layer Caching** - Redis session + application cache
- **Horizontal Scaling** - Load balancer-ready, stateless workers
- **Gunicorn Optimization** - Threaded workers for high concurrency

## Quick Start

### Prerequisites

- Docker & Docker Compose
- PostgreSQL 15+ (optional, for external DB)
- Redis 7+ (included)
- Python 3.11+ (for development)

### 1. Clone & Configure

```bash
git clone <repository-url>
cd pm
cp .env.example .env
# Edit .env with your settings
```

**Important configuration:**
```bash
# Set strong secret key
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# Configure database (postgres required for production)
POSTGRES_PASSWORD=your_secure_password

# Set alert email (for watchdog & reports)
ALERT_EMAIL_ADDRESS=lawrencemulindwa48@gmail.com
ALERT_EMAIL_PASSWORD=your_gmail_app_password
```

### 2. Start All Services

```bash
# Start entire stack (web, db, redis, monitoring)
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f web
```

Services started:
- **Web App**: http://localhost:5001
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin / admin123)
- **Alertmanager**: http://localhost:9093

### 3. First-Time Setup

When you first visit http://localhost:5001:

1. You'll see a **"First time setup?"** banner on the login page
2. Click **"Create your first admin account"**
3. Fill in your details (email, name, password)
4. Account created! Log in immediately

**Note:** After this, no additional admin accounts can be created through self-service. Contact system administrator for additional admin access.

### 4. Access Monitoring

```bash
# Health check
curl http://localhost:5001/health

# Prometheus metrics
curl http://localhost:5001/metrics

# View Grafana dashboards
open http://localhost:3000
```

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Load Balancer (optional)                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Gunicorn      │
                    │   (2 workers ×  │
                    │    4 threads)   │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
    ┌───▼────┐          ┌────▼─────┐        ┌────▼─────┐
    │Postgres│          │  Redis   │        │   S3     │
    │(primary)│          │ (cache)  │        │   (optional)│
    └────────┘          └──────────┘        └──────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
    ┌───▼────┐          ┌────▼─────┐        ┌────▼─────┐
    │Celery  │          │Watchdog  │        │ Daily    │
    │Worker  │          │Monitor   │        │Reporter  │
    └────────┘          └──────────┘        └──────────┘
```

### Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Backend** | Flask 3.1 | Web framework |
| **Database** | PostgreSQL 15 | Relational data store |
| **Cache** | Redis 7 | Session + caching |
| **Queue** | Celery + Redis | Async task processing |
| **WSGI** | Gunicorn | Production server |
| **Monitoring** | Prometheus | Metrics collection |
| **Visualization** | Grafana | Dashboards |
| **Logs** | Loki | Log aggregation |
| **Tracing** | Tempo | Distributed tracing |
| **Alerting** | Alertmanager | Email alerts |

## Configuration

All configuration via environment variables. See `.env.example` for full list.

### Key Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | **REQUIRED** | Flask secret (min 32 chars) |
| `DATABASE_URL` | **REQUIRED** | PostgreSQL connection string |
| `REDIS_URL` | redis://redis:6379/0 | Redis connection |
| `ALERT_EMAIL_ADDRESS` | - | Email for alerts/watchdog |
| `ALERT_EMAIL_PASSWORD` | - | App password for email |
| `WATCHDOG_ENABLED` | true | Enable watchdog monitoring |
| `WATCHDOG_INTERVAL` | 300 | Check interval (seconds) |
| `REPORT_INTERVAL_MINUTES` | 90 | Unified Watchdog AI report interval (minutes) |
| `REPORT_TIME` | 09:00 | Fallback daily report send time if interval mode is unset |

### Production Checklist

- [ ] Set strong `SECRET_KEY` (use `secrets.token_hex(32)`)
- [ ] Use PostgreSQL (not SQLite) for production
- [ ] Set `SESSION_COOKIE_SECURE=1`, `REMEMBER_COOKIE_SECURE=1`, and `PREFERRED_URL_SCHEME=https`
- [ ] Configure `PUBLIC_BASE_URL` to actual domain
- [ ] Set up SSL/TLS certificates (let's encrypt, Cloudflare)
- [ ] Configure email credentials for alerts
- [ ] Set resource limits in `docker-compose.yml`
- [ ] Enable Prometheus remote write (optional)
- [ ] Set up log aggregation (Loki, ELK, etc.)
- [ ] Create database backups strategy

## Monitoring & Alerts

### Health Check URL

Include in load balancer or external monitoring:

```
GET http://localhost:5001/health
```

Expected: `200 OK` with JSON body

### Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: 'pm-system'
    static_configs:
      - targets: ['localhost:5001']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

### Alert Rules

Pre-configured alerts:

- **Critical**: Database/Redis down, disk >95%, CPU >95%, error rate >5%
- **Warning**: Disk >85%, memory >85%, response time >2s

Alerts email to `lawrencemulindwa48@gmail.com`.

### Grafana Dashboards

Access at http://localhost:3000:

- **PM System Overview** - System health, user count, activity metrics
- **Performance** - Request latency, throughput, error rate
- **Security** - Login patterns, blocked users, audit events
- **Infrastructure** - CPU, memory, disk, network

## Usage

### User Roles

| Role | Permissions |
|------|-------------|
| **Developer** | Full admin: user mgmt, security, settings |
| **General Manager** | Dashboard, approvals, user overview, consumables |
| **Manager** | Dashboard, desk activities, approvals, consumables |
| **Staff** | Dashboard, desk activities, view forms |
| **Technician** | Field RCA, calendar, own submissions |

### Self-Service Developer Creation

To create the initial developer:

```
GET  /admin/self-service/create-developer  →  Show form
POST /admin/self-service/create-developer  →  Create account
```

**Constraints:**
- Only works when ZERO developers exist
- After first developer, endpoint returns 403
- Cannot create duplicate developers
- Password min 8 characters

### Common Tasks

```python
# Query audit logs
from model import AuditLog, db
from datetime import datetime, timedelta

last_24h = datetime.utcnow() - timedelta(hours=24)
logs = AuditLog.query.filter(
    AuditLog.created_at >= last_24h
).order_by(AuditLog.created_at.desc()).all()

# Generate PDF report for activity
from app import create_app
app = create_app()
with app.app_context():
    activity = Activity.query.get(123)
    pdf_buffer = build_activity_pdf_buffer(activity, app.config['UPLOAD_FOLDER'])
    with open('report.pdf', 'wb') as f:
        f.write(pdf_buffer.getvalue())
```

## Development

### Local Setup (No Docker)

```bash
# Create virtualenv
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up .env file
cp .env.example .env
# Edit .env: set DATABASE_URL to local postgres

# Initialize DB
flask db upgrade

# Run dev server
python app.py
# Or
flask run --port=5001
```

### Running Tests

```bash
pytest
pytest --cov=pm_app
```

### Code Style

```bash
flake8
black .
```

## Troubleshooting

### Redis Connection Failing

Check Redis is running:
```bash
docker-compose ps redis
docker-compose logs redis
```

Restart if needed:
```bash
docker-compose restart redis
```

### Health Check Shows Degraded

Check individual components:
```bash
curl http://localhost:5001/health | jq
```

Look for `"status": "critical"` in response.

### Emails Not Sending

1. Verify credentials in `.env`
2. Use Gmail app password (not regular password)
3. Check `watchdog.log` and `reporter.log`

### Database Migrations

If schema changes:
```bash
flask db migrate -m "description"
flask db upgrade
```

## Performance Tuning

### Scale Workers

Edit `Dockerfile` CMD:

```dockerfile
# More CPU cores → more workers
CMD ["gunicorn", "--workers", "4", "--threads", "2", "--worker-class", "gthread", ...]
```

**Formula:** `workers = (2 × CPU_cores) + 1`

### Database Connection Pool

Adjust in `app.py`:
```python
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 30,        # Base connections per worker
    'max_overflow': 50,     # Burst capacity
    'pool_recycle': 1800,   # Recycle after 30 min
}
```

**Formula:** `pool_size × worker_count` should be ≤ `max_connections` in PostgreSQL

### Celery Concurrency

In `docker-compose.yml`:
```yaml
celery:
  command: celery -A pm_app.celery worker --loglevel=info --concurrency=4
```

**Formula:** `concurrency ≤ (CPU_cores × 2)`

## Security

### Audit Trail

All actions logged to `audit_logs` table:

- Authentication events (login, logout, failures)
- Authorization checks (permissions, access denied)
- Data modifications (create, update, delete)
- System events (config changes, maintenance)

Query audit:
```sql
SELECT * FROM audit_logs 
WHERE created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;
```

### Rate Limiting

Per-IP rate limits on auth endpoints (configurable):

```python
# Flask-Limiter defaults
"200 per day", "50 per hour"  # Login endpoints
"1000 per day"               # API endpoints
```

### Password Security

- PBKDF2-SHA256 with 260,000 iterations (configurable)
- Minimum 8 characters
- Strong hash verification

## Backup & Recovery

### Database Backup

```bash
# Backup
docker-compose exec db pg_dump -U pm_user pm_db > backup_$(date +%Y%m%d).sql

# Restore
docker-compose exec -T db psql -U pm_user pm_db < backup_20260508.sql
```

### Volume Backups

```bash
# Backup PostgreSQL data volume
docker run --rm -v pm_postgres-data:/data -v $(pwd):/backup alpine tar czf /backup/postgres.tar.gz /data

# Restore
docker run --rm -v pm_postgres-data:/data -v $(pwd):/backup alpine tar xzf /backup/postgres.tar.gz
```

## Support

For questions or issues:

- **Email**: lawrencemulindwa48@gmail.com
- **Documentation**: See `/docs` folder
- **Monitoring Guide**: `docs/MONITORING.md`

## License

Proprietary - All rights reserved

---

**Enterprise Edition** | **Version 1.0.0** | Built with ❤️ by Soliton Telmec
