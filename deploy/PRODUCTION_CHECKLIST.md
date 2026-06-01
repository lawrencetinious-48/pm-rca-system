Production deployment checklist for PM/RCA system

1. Secrets and environment
   - Set `DATABASE_URL` to a PostgreSQL DSN using `psycopg` (e.g. `postgresql+psycopg://user:pass@host:5432/pm_db`).
   - Set `SECRET_KEY` to a 32+ byte random value.
   - Set `POSTGRES_PASSWORD` for local docker-compose deployments (`.env.prod`).
   - Ensure `SESSION_COOKIE_SECURE=1` and `REMEMBER_COOKIE_SECURE=1` in production.

2. Build & Run (Docker Compose)
   ```bash
   docker build -t pm-app:prod .
   docker-compose -f docker-compose.prod.yml up -d --build
   ```

3. Health checks
   - Application exposes `/health` for readiness and liveness checks.
   - PostgreSQL service uses `pg_isready` in docker-compose healthcheck.

4. Logging & rotation
   - Ensure host `./logs` is writable by container or configure centralized logging (fluentd, Promtail).
   - Rotate logs; the container image preserves `/app/logs`.

5. Monitoring
   - Provision Prometheus + Grafana scraping the `/metrics` endpoint if enabled.
   - Configure alertmanager using `alertmanager/alertmanager.yml`.

6. Backups
   - Regular PostgreSQL backups (pg_dump) and secure storage for backups.

7. Security
   - Run behind TLS (Caddy is included in `docker-compose.prod.yml`).
   - Limit access to management endpoints and secure self-service registration.

8. Scaling
   - Use dedicated workers for Celery (see `worker` service in docker-compose).
   - Tune Gunicorn workers/threads in `Dockerfile` via environment variables.

9. CI/CD
   - CI should run `pytest` and `flake8` on pull requests.
   - Fail builds on `LegacyAPIWarning` to prevent regressions.

10. Post-deploy sanity checks
   - Smoke test login, create activity, and PDF generation paths.
   - Verify email sending via configured SMTP or webhook.

For more advanced setups, consider container orchestration (Kubernetes) and secret management (Vault, AWS Secrets Manager).