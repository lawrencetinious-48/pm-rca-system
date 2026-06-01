# Deployment Checklist

Use this checklist when deploying the PM/RCA System to production.

## Pre-Deployment

### Environment Setup
- [ ] Server(s) provisioned (Ubuntu 22.04+ or equivalent)
- [ ] Docker & Docker Compose installed
- [ ] SSL certificates obtained (Let's Encrypt or commercial)
- [ ] Domain DNS configured (A record → server IP)
- [ ] Firewall rules: 80, 443, 5001 (optional), 9090, 3000 (monitoring only from trusted IPs)

### Configuration Files
- [ ] Copy `.env.example` to `.env`
- [ ] Generate strong `SECRET_KEY` (32+ chars, random)
- [ ] Set `POSTGRES_PASSWORD` to strong value
- [ ] Set `ALERT_EMAIL_ADDRESS` to your Gmail address
- [ ] Set `ALERT_EMAIL_PASSWORD` to your Gmail App Password (required for Gmail SMTP)
- [ ] Set `ALERT_SMTP_HOST=smtp.gmail.com`
- [ ] Set `ALERT_SMTP_PORT=465`
- [ ] Set `ALERT_SMTP_USE_SSL=1`
- [ ] Set `ALERT_SMTP_USE_TLS=0`
- [ ] Set `PUBLIC_BASE_URL=https://yourdomain.com`
- [ ] Enable `SESSION_COOKIE_SECURE=1`
- [ ] Enable `REMEMBER_COOKIE_SECURE=1`
- [ ] Set `PREFERRED_URL_SCHEME=https`
- [ ] Configure `WATCHDOG_ENABLED=true`
- [ ] Set `REPORT_INTERVAL_MINUTES=90` for the unified Watchdog AI report (or `REPORT_TIME` for fallback daily send)
- [ ] Set `WATCHDOG_SEND_PERIODIC_SUMMARY=0`
- [ ] Configure Postgres backups and retention policy
- [ ] Adjust resource limits in `docker-compose.yml` based on server specs

### Validation
- [ ] Run full test suite: `pytest tests -q`
- [ ] Verify health endpoint: `curl http://localhost:5001/__health`
- [ ] Verify Prometheus metrics endpoint: `curl http://localhost:5001/metrics`
- [ ] Confirm monitoring stack targets are healthy before release

### Database
- [ ] PostgreSQL version 15+ available
- [ ] Database created: `pm_db`
- [ ] User created: `pm_user` with password
- [ ] pg_hba.conf configured for password auth
- [ ] Test connection: `psql -U pm_user -d pm_db -h localhost`

### Monitoring Stack
- [ ] Prometheus data directory created: `mkdir -p prometheus`
- [ ] Grafana data directory created: `mkdir -p grafana`
- [ ] Loki config exists: `loki/loki-local-config.yaml`
- [ ] Tempo config exists: `tempo/tempo.yaml`
- [ ] Alertmanager config exists: `alertmanager/alertmanager.yml`
- [ ] Ports 9090, 3000, 3100, 3200, 9093 not in use

## Deployment Steps

### 1. Pull Latest Code
```bash
cd /opt/pm
git pull origin main
```

### 2. Build Docker Images
```bash
docker-compose build --no-cache
```

### 3. Run Database Migrations
```bash
docker-compose up -d db
sleep 10  # Wait for DB to be ready
docker-compose exec web flask db upgrade
```

### 4. Initialize Monitoring
```bash
# Prometheus rules and Grafana dashboards auto-loaded from provisioning dirs
# No additional steps needed - just start stack
```

### 5. Start All Services
```bash
docker-compose up -d
```

### 6. Verify Services
```bash
docker-compose ps

# Should see all services: web, db, redis, prometheus, grafana, loki, tempo, alertmanager
```

### 7. Check Health
```bash
curl https://yourdomain.com/health | jq

# Should return: {"status":"healthy",...}
```

### 8. Test Metrics
```bash
curl https://yourdomain.com/metrics | head -20

# Should see prometheus metrics output
```

### 9. Verify Monitoring Stack
```bash
# Prometheus targets
open https://yourdomain.com:9090/targets  # If accessible
# All targets should show "UP"

# Grafana
open http://yourdomain.com:3000  # Login: admin / admin123 (change immediately!)
# Dashboards → import PM System dashboards
```

### 10. Check First-Time Setup

Visit `https://yourdomain.com`:

- [ ] Login page loads
- [ ] "First time setup?" banner visible (if no developer exists)
- [ ] Self-service form accessible via link
- [ ] Can create admin account
- [ ] Login works after creation

## Post-Deployment

### Security Hardening
- [ ] Change Grafana admin password
- [ ] Configure Grafana with auth proxy (optional)
- [ ] Set up SSL auto-renewal (certbot)
- [ ] Restrict monitoring ports (9090, 3000) to admin IPs only
- [ ] Enable fail2ban or similar SSH protection
- [ ] Review and restrict database permissions
- [ ] Enable PostgreSQL SSL connections
- [ ] Rotate SECRET_KEY if exposed
- [ ] Set up regular security updates

### Monitoring Configuration
- [ ] Verify all Prometheus targets are UP
- [ ] Check Grafana dashboards are populated
- [ ] Test alert routing via Alertmanager:
  ```bash
  # Send test alert
  curl -XPOST http://localhost:9093/-/reload
  ```
- [ ] Confirm watchdog emails received at lawrencemulindwa48@gmail.com
- [ ] Verify daily reporter email (wait for scheduled time or trigger manually)

### Backup Strategy
- [ ] Database backup job configured (cron or script)
- [ ] Volume backup scheduled (uploads, logs)
- [ ] Backup retention policy set
- [ ] Backup restoration tested

### Performance Tuning
- [ ] Review Gunicorn worker count matches CPU cores
- [ ] Adjust DB pool size: `SQLALCHEMY_ENGINE_OPTIONS['pool_size']`
- [ ] Monitor memory usage over first 24h
- [ ] Tune Celery concurrency if using async tasks
- [ ] Set up log rotation (already configured in app)

### Documentation
- [ ] Update README with production URL
- [ ] Document admin credentials (securely!)
- [ ] Create runbook for common operations
- [ ] Document incident response procedure
- [ ] Add monitoring dashboards to team wiki

## Ongoing Maintenance

### Daily
- [ ] Check watchdog alert emails (none = good!)
- [ ] Review daily reporter email
- [ ] Monitor disk space on server

### Weekly
- [ ] Review Grafana dashboards for trends
- [ ] Check audit logs for security events
- [ ] Review failed logins and blocked users
- [ ] Backup verification (spot check)

### Monthly
- [ ] Security updates: `docker-compose pull && docker-compose up -d`
- [ ] Database maintenance: `VACUUM ANALYZE;`
- [ ] Review and prune old log files
- [ ] Check SSL certificate expiration
- [ ] Review and update dependencies
- [ ] Test disaster recovery (restore from backup)

### Quarterly
- [ ] Security audit of audit logs
- [ ] Performance review and capacity planning
- [ ] Update documentation
- [ ] Team training on monitoring tools

## Troubleshooting

### Service Won't Start
```bash
# Check logs
docker-compose logs web
docker-compose logs db

# Common issues:
# - SECRET_KEY not set → check .env
# - PostgreSQL not ready → wait longer, check DB credentials
# - Port in use → change ports in docker-compose.yml
```

### No Metrics in Prometheus
```bash
# Verify /metrics endpoint
curl https://yourdomain.com/metrics

# Check Prometheus targets UI
# Check if scrape job is configured correctly
```

### Emails Not Sending
```bash
# Test email config
python -c "import smtplib; ..."

# Common Gmail issues:
# - Use App Password (2FA required)
# - Allow less secure apps disabled → use App Password
```

### High Memory Usage
```bash
# Check container stats
docker stats

# Adjust Gunicorn workers down if needed
# Reduce pool_size in SQLALCHEMY_ENGINE_OPTIONS
```

### Database Connection Errors
```bash
# Check PostgreSQL max_connections
docker-compose exec db psql -U pm_user -c "SHOW max_connections;"

# Increase if pool_size + overflow exceeds limit
# default max_connections = 100
```

## Emergency Contacts

- **System Admin**: lawrencemulindwa48@gmail.com
- **Monitoring**: http://yourdomain.com:3000 (Grafana dashboards)
- **Metrics**: http://yourdomain.com:9090 (Prometheus)
- **Health**: http://yourdomain.com/health

## Upgrade Procedure

1. Backup database & volumes
2. Pull new code
3. Update dependencies: `docker-compose build`
4. Run migrations: `docker-compose exec web flask db upgrade`
5. Restart services: `docker-compose up -d`
6. Verify health: `curl /health`
7. Monitor for 24h

---

**Last Updated:** 2026-05-08  
**Version:** 1.0.0  
**Environment:** Production
