# PM System Monitoring & Observability Guide

## Overview

The PM/RCA System now includes enterprise-grade monitoring, alerting, and self-service provisioning capabilities.

## Monitoring Stack

The system uses a modern observability stack:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Prometheus    │────│     Grafana     │────│   Alertmanager  │
│   (Metrics)     │    │   (Dashboards)  │    │   (Alerts)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     PM App      │    │      Loki       │    │   Watchdog      │
│   (/metrics)    │    │   (Logs)        │    │   Service       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌─────────────────┐
│     Tempo       │    │  Daily Reporter │
│  (Traces)       │    │   (Reports)     │
└─────────────────┘    └─────────────────┘
```

## Components

### 1. Health Check Endpoint

**Endpoint:** `GET /health`

Comprehensive health check that monitors:

- Database connectivity
- Redis availability
- Disk space usage
- Memory usage
- CPU usage

**Response format:**
```json
{
  "status": "healthy|degraded|critical",
  "timestamp": "2026-05-08T12:00:00",
  "checks": {
    "database": {"status": "healthy", "message": "Database connection OK"},
    "redis": {"status": "healthy", "message": "Redis connection OK"},
    "disk_space": {"status": "healthy", "message": "Disk 45.2% used"},
    "memory": {"status": "healthy", "message": "Memory 62.1% used"},
    "cpu": {"status": "healthy", "message": "CPU 12.5%"}
  },
  "uptime": 1234567.89
}
```

**Status codes:**
- `200`: Healthy or degraded
- `503`: Critical/unhealthy

### 2. Prometheus Metrics Endpoint

**Endpoint:** `GET /metrics`

Standard Prometheus exposition format. Exposes metrics:

- `http_requests_total` - Counter of all HTTP requests by method, endpoint, status
- `http_request_duration_seconds` - Histogram of request latency
- `active_users_total` - Gauge of active user count
- `total_users_total` - Gauge of total registered users
- `db_pool_connections` - Gauge of DB pool usage
- `memory_usage_percent` - System memory usage
- `cpu_usage_percent` - System CPU usage
- `disk_usage_percent` - System disk usage
- `pm_system_info` - Static info about deployment

### 3. Watchdog Service

Continuous background service that monitors system health every 5 minutes.

**What it monitors:**
- Database connectivity
- Redis connectivity  
- Disk space (>90% triggers warning, >95% critical)
- Memory usage (>85% warning, >95% critical)
- CPU usage (>85% warning, >95% critical)
- Application response time (>2s warning, >5s critical)
- Recent error logs (error rate >5% triggers alert)

**Alerting:**
- Immediate email alerts to `lawrencemulindwa48@gmail.com`
- 30-minute cooldown between similar alerts
- Critical alerts use red subject line
- Warnings use yellow subject line
- All alerts include timestamp, severity, and details

**Configuration via environment variables:**
```bash
WATCHDOG_ENABLED=true
WATCHDOG_INTERVAL=300  # 5 minutes
WATCHDOG_RESPONSE_TIME_THRESHOLD=2.0
WATCHDOG_CPU_THRESHOLD=90.0
WATCHDOG_MEMORY_THRESHOLD=90.0
WATCHDOG_DISK_THRESHOLD=90.0
```

### 4. Daily Reporter Service

Runs as the unified Watchdog AI report pipeline, sending a rich email every configured interval.

**Report includes:**
- System uptime
- User metrics (total, new, blocked, logins)
- Activity summary (PMs, RCAs, Snags, approvals)
- SLA status (overdue, due soon)
- Performance metrics (avg processing time)
- Error count from last 24h
- Security metrics (failed logins)
- Full Watchdog health checks and AI-generated insights

**Email format:** HTML + plain text multipart

**Configuration:**
```bash
REPORT_INTERVAL_MINUTES=90   # Send unified report every 90 minutes
REPORT_TIME=09:00            # Fallback daily send time if interval mode is unset
REPORT_EMAIL=lawrencemulindwa48@gmail.com
REPORT_RETENTION_DAYS=30
WATCHDOG_SEND_PERIODIC_SUMMARY=0
```

### 5. Audit Logging

All security events are logged to the `audit_logs` database table.

**Logged events:**
- Successful logins
- Failed login attempts
- CSRF failures
- Role mismatches
- Admin account creation (self-service)
- User account changes
- Permission modifications

**Query audit logs:**
```python
from model import AuditLog
from datetime import datetime, timedelta

# Last 24 hours
recent = AuditLog.query.filter(
    AuditLog.created_at >= datetime.utcnow() - timedelta(hours=24)
).order_by(AuditLog.created_at.desc()).all()

for entry in recent:
    print(f"{entry.created_at} - {entry.action} - User: {entry.user_id}")
```

## Setup & Deployment

### 1. Start Monitoring Stack

The full stack is defined in `docker-compose.yml`. To start everything:

```bash
# Start all services including monitoring
docker-compose up -d

# View monitoring services
docker-compose ps | grep -E "prometheus|grafana|loki|tempo|alertmanager"

# Access Grafana: http://localhost:3000 (admin / admin123)
# Access Prometheus: http://localhost:9090
```

### 2. Configure Alertmanager Email

Edit `alertmanager/alertmanager.yml` to configure email recipients:

```yaml
receivers:
  - name: 'email-notifications'
    email_configs:
      - to: 'lawrencemulindwa48@gmail.com'
        send_resolved: true
        from: '${ALERT_EMAIL_ADDRESS}'
        smtp_auth_username: '${ALERT_EMAIL_ADDRESS}'
        smtp_auth_password: '${ALERT_EMAIL_PASSWORD}'
```

### 3. Grafana Dashboards

Pre-configured dashboards in `grafana/provisioning/dashboards/`:

- **PM System Overview** - Key metrics, activity trends, health status
- **User Analytics** - User growth, login patterns, role distribution  
- **Performance** - Response times, error rates, SLA compliance
- **Security** - Login attempts, blocked users, audit events

Import custom dashboards via Grafana UI or place JSON files in `grafana/dashboards/`.

### 4. Access Metrics

```bash
# From within Docker network
curl http://localhost:9090/metrics  # Prometheus own metrics
curl http://localhost:5001/metrics  # PM app metrics

# Or from host
curl http://localhost:5001/metrics
```

## Self-Service Admin Onboarding

### First-Time Setup Flow

1. **Customer purchases system** → System has no admin account
2. **Visit login page** → See "First time setup?" banner
3. **Click "Create your first admin account"**
4. **Fill form** → Email, full name, password
5. **Submit** → Admin account created
6. **Login** → Full admin access

**Key constraint:** Only ONE admin account can be created. After that, the self-service endpoint returns 403 with locked message.

### Implementation Details

**Route:** `GET/POST /admin/self-service/create-developer`

**Templates:**
- `self_service_register.html` - Registration form
- `self_service_locked.html` - Locked message (developer exists)

**Logic:**
```python
if User.query.filter_by(role="developer").first():
    return render_template("self_service_locked.html"), 403
```

### Login Page Integration

On `login.html`, a banner is shown only when no developer exists:

```jinja2
{% if not developer_exists %}
<div class="alert alert-success">
  <strong>First time setup?</strong> 
  <a href="{{ url_for('self_service_create_developer') }}">
    Create your first admin account
  </a>
</div>
{% endif %}
```

## Alerts & Notifications

### Alert Routing

All alerts go through Alertmanager which can route based on severity:

- **Critical** → Immediate email to admin
- **Warning** → Daily summary email

### Custom Alert Rules

Add rules to `prometheus/prometheus.yml`:

```yaml
groups:
  - name: pm_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          
      - alert: HighResponseTime
        expr: histogram_quantile(0.95, http_request_duration_seconds) > 2
        for: 5m
        labels:
          severity: warning
```

## Database Migrations

When deploying to production, run migrations:

```bash
# Inside Docker container
docker-compose exec web flask db upgrade

# Or manually
docker-compose exec web python -m flask db upgrade head
```

The `postgres-init.sql` file creates the `audit_logs` table and indexes on startup.

## Log Management

### Structured Logging

Application logs are JSON-formatted for easy parsing by Loki:

```json
{
  "time": "2026-05-08T12:00:00",
  "level": "INFO",
  "message": "Request completed",
  "request_id": "abc123",
  "method": "GET",
  "path": "/dashboard",
  "status": 200,
  "duration_ms": 45.2,
  "remote_addr": "192.168.1.1"
}
```

### Log Retention

- Application logs: 5 rotating files, 5MB each (configurable in `setup_logging()`)
- Access logs: JSON format, stored in `logs/`
- Watchdog logs: `logs/watchdog.log`
- Reporter logs: `logs/reporter.log`

## Performance Tuning

### Gunicorn Settings

Current configuration in `Dockerfile`:
- Workers: 2 (static)
- Threads: 4 per worker
- Worker class: `gthread` for async I/O
- Max requests: 1000 (prevents memory leaks)
- Jitter: 100 (prevents all workers restarting simultaneously)

**Adjust based on CPU cores:**
```bash
# More CPU cores → more workers
# Rule of thumb: (2 * cores) + 1
CMD ["gunicorn", "--workers", "5", "--threads", "2", "--worker-class", "gthread", ...]
```

### Database Connection Pool

SQLAlchemy pool settings in `app.py`:
```python
SQLALCHEMY_ENGINE_OPTIONS = {
    'poolclass': QueuePool,
    'pool_size': 20,          # Base connections
    'max_overflow': 30,        # Extra connections under load
    'pool_pre_ping': True,     # Check connections before use
    'pool_recycle': 3600,      # Recycle after 1 hour
    'pool_timeout': 30,        # Wait 30s for connection
}
```

### Redis Configuration

Redis is configured with:
- Max memory: 256MB
- Policy: allkeys-lru (evict least recently used)
- Persistence: AOF (Append Only File) enabled

## Troubleshooting

### Health Check Returns 503

Check logs:
```bash
docker-compose logs web | grep -i "health"
docker-compose logs db
docker-compose logs redis
```

### Prometheus Metrics Missing

```bash
# Install client library
pip install prometheus-client

# Verify endpoint
curl http://localhost:5001/metrics
```

### Watchdog Not Sending Emails

```bash
# Check watchdog logs
docker-compose logs watchdog

# Verify email credentials are set in .env:
ALERT_EMAIL_ADDRESS and ALERT_EMAIL_PASSWORD

# Test email manually
python -c "import smtplib; ..."
```

### Grafana Not Showing Data

1. Check Prometheus is scraping targets: http://localhost:9090/targets
2. Verify data source configuration in Grafana
3. Check Loki/Tempo are running: `docker-compose ps`

## Additional Resources

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [Tempo Documentation](https://grafana.com/docs/tempo/latest/)
- [Celery Documentation](https://docs.celeryproject.org/)

## Support

For issues or questions:
- Email: lawrencemulindwa48@gmail.com
- Repository: [GitHub Issues]
