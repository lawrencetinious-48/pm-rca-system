# Environment File Guide

This repo uses environment files to store configuration for development and production.

## Which files are used and why

- `.env.example`
  - Template for local development.
  - Copy to `.env` when you want to run the app locally.
  - Contains example values and comments only.

- `.env.prod.example`
  - Template for production deployment.
  - Copy to `.env.prod` and fill with real secrets.
  - Contains production-safe defaults and required production settings.

- `.env`
  - Local runtime file for the current environment.
  - Used for development and staging.
  - Should never be committed to Git.
  - This repo now ignores `.env` in `.gitignore`.

- `.env.prod`
  - Local production runtime file.
  - Used by `docker-compose.prod.yml`.
  - Should never be committed to Git.
  - This repo now ignores `.env.prod` in `.gitignore`.

## Recommended setup

### Development

1. Copy the template:
   ```bash
   copy .env.example .env
   ```
2. Update values for local usage.
3. Use `.env` while working in development.

### Production

1. Copy the production template:
   ```bash
   copy .env.prod.example .env.prod
   ```
2. Set real production values.
3. Run production compose with:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

## Important rules for production

- `APP_ENV` must be `production`.
- `DATABASE_URL` must point to PostgreSQL with `psycopg`:
  `postgresql+psycopg://user:pass@host:5432/dbname`
- `SESSION_COOKIE_SECURE` and `REMEMBER_COOKIE_SECURE` should be `1`.
- Use a strong `SECRET_KEY`.
- Set `SELF_SERVICE_ENABLED=0` in production unless you need a temporary self-service admin registration window.
- Do not use SQLite in production.

## SQLite and local test data

- SQLite is only for development and local testing.
- In production, the system should use PostgreSQL.
- Any test forms, sample users, or local SQLite data should not be copied into production.
- Start production with a clean PostgreSQL database and create new production users.

## One-time admin / bootstrap workflow

### Recommended: use `scripts/create_admin.py`

This script creates the first `developer` account safely without relying on the self-service endpoint.

Usage:
```bash
python scripts/create_admin.py --email admin@example.com --name "Admin User" --password "StrongPassword123!"
```

### Self-service admin creation

The self-service endpoint exists but is hidden by default in production.

- URL: `/admin/self-service/create-developer`
- Only works if `SELF_SERVICE_ENABLED=1`.
- Only works when no `developer` role user exists.
- If a developer already exists, the endpoint returns 404.

### What should happen in production

1. Deploy with a clean PostgreSQL database.
2. Create the first admin account with `scripts/create_admin.py` or temporarily enable self-service.
3. Log in as the new admin.
4. If you enabled `SELF_SERVICE_ENABLED=1`, set it back to `0` after the account is created.

## Summary

- Keep `.env.example` and `.env.prod.example` in the repo as templates.
- Keep `.env` and `.env.prod` local and private.
- Use PostgreSQL for production.
- Use the admin bootstrap script for the first administrator.
- Do not copy SQLite/test data into production.
