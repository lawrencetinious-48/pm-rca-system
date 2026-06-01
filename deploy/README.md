Deployment guide
================

Overview
--------
This document describes a simple Docker-based production deployment for the PM app.

Prerequisites
-------------
- Docker Engine and Docker Compose installed on the host.
- TLS certificates (Caddy will optionally obtain them automatically if DNS/ports are reachable).
- A PostgreSQL-compatible storage (we provide Postgres in the compose stack).
- A strong `SECRET_KEY` of >=32 bytes hex printed with: `python -c "import secrets; print(secrets.token_hex(32))"`

Quick start (single-host)
-------------------------
1. Copy `.env.prod.example` to `.env.prod` and fill in values (especially `SECRET_KEY` and `POSTGRES_PASSWORD`).
2. Build the application image and start the stack:

```bash
# from repository root
docker build -t myorg/pm:prod .
docker tag myorg/pm:prod myorg/pm:latest
# push to your registry if using remote hosts
# docker push myorg/pm:prod

# start compose
docker compose -f docker-compose.prod.yml up -d
```

Run database migrations
-----------------------
Apply Alembic migrations after the app image is available:

```bash
# run migration container (uses image built above)
docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
```

Health checks and logs
----------------------
- App health endpoint: `GET /health` (configured in the compose healthcheck).
- Logs are mounted to `./logs` in the repo root.
- Run the full test suite before deployment: `pytest tests -q`
- Validate metrics endpoint: `curl http://localhost:5001/metrics`

Notes and production hardening
------------------------------
- Always set `SESSION_COOKIE_SECURE=1`, `REMEMBER_COOKIE_SECURE=1`, and `PREFERRED_URL_SCHEME=https` for internet-facing deployments.
- Use an external managed database and managed Redis in high-availability environments instead of local containers.
- Configure backups for Postgres (cron + `pg_dump` or cloud provider backups).
- Use a registry and immutable image tags; automate builds and scanning in CI/CD.

Rollback and migrations
-----------------------
- Test migrations in staging before applying to production.
- Keep daily logical backups of the DB prior to running schema changes.

Contact
-------
If you need a hosted deploy manifest (Kubernetes, ECS, or systemd unit files), say which target and I will generate it.
