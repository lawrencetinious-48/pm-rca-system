# System Maintenance Guide

## Overview
This guide documents maintenance procedures to prevent system breakage over time. Follow these steps regularly to keep the PM application healthy.

## Critical Issues Fixed (April 17, 2026)

### 1. ✅ Production Cookie Security
**Issue**: Session cookies not marked as Secure for HTTPS
**Fix**: Updated `.env` with:
```env
SESSION_COOKIE_SECURE=1
REMEMBER_COOKIE_SECURE=1
PREFERRED_URL_SCHEME=https
```
**Impact**: Prevents session hijacking via HTTP interception

### 2. ✅ Test Suite Stability
**Issue**: Pytest teardown hangs causing flaky tests
**Fix**: 
- Updated `pytest.ini` with timeout settings (30s per test)
- Improved app fixture teardown in `tests/conftest.py`
- Added `pytest-timeout` to requirements.txt

### 3. ✅ Virtual Environment Management
**Issue**: Python commands timing out, environment corruption
**Fix**: Created rebuild scripts for clean venv setup

---

## Maintenance Scripts

### 1. Rebuild Virtual Environment
Use when environment becomes unresponsive or tests fail with import errors.

**Windows (PowerShell):**
```powershell
.\rebuild_venv.ps1
```

**Windows (cmd.exe):**
```batch
rebuild_venv.bat
```

**What it does:**
- Removes old `.venv` directory
- Creates fresh Python virtual environment
- Upgrades pip, setuptools, wheel
- Installs all requirements from `requirements.txt`

**When to use:**
- After major dependency updates
- If pip commands start timing out
- When tests fail with import errors
- Quarterly as preventative maintenance

### 2. Health Check
Run regularly to detect issues early before they become critical.

```powershell
.\.venv\Scripts\python.exe .\health_check.py
```

**Checks:**
- Python environment integrity
- pip package database
- Core modules compile successfully
- Test suite can be collected
- Code passes linting standards

**When to use:**
- After deploying changes
- Before committing code
- Weekly as routine check
- After environment updates

---

## Quarterly Maintenance Checklist

### Month 1: Dependency Review
```powershell
.\.venv\Scripts\pip.exe list --outdated
```
- Check for security updates
- Update packages with `pip install --upgrade package-name`
- Test suite after updates
- Commit updated `requirements.txt` if changes made

### Month 2: Code Quality
```powershell
.\.venv\Scripts\python.exe -m flake8 app.py pm_app --statistics
```
- Review linting violations
- Fix style issues
- Consider richer type hints with `pydantic` if not already used

### Month 3: Test Coverage
```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app --cov=pm_app --cov-report=html
```
- Generate coverage report
- Identify untested code paths
- Add tests for critical paths
- Review coverage trends

### Month 4: Security Audit
```powershell
.\.venv\Scripts\pip.exe install pip-audit
.\.venv\Scripts\python.exe -m pip_audit
```
- Check for known security vulnerabilities
- Update affected packages immediately
- Review CVE details if any found

---

## Configuration Best Practices

### Environment Variables
- **Always** use `.env` for deployment-specific settings
- **Never** commit `.env` files to version control
- Review `.env.example` before deployment
- **Production-critical**:
  - `SECRET_KEY`: Use cryptographically strong random hex (64 chars min)
  - `SESSION_COOKIE_SECURE`: Set to `1` behind HTTPS
  - `DATABASE_URL`: Use PostgreSQL in production, never SQLite
  - `APP_ENV`: Must be `production`

### Database
- SQLite is for development/testing only
- Production must use PostgreSQL (`postgresql+psycopg://...`)
- Always backup database before migrations
- Test migrations in staging first

### Monitoring
- Monitor error logs for patterns
- Set up alerts for test failures
- Log database query performance
- Track API response times

---

## Troubleshooting

### Problem: Tests timeout or hang
**Solution:**
1. Run health_check.py
2. Rebuild venv if needed
3. Increase timeout in pytest.ini if legitimate slow tests

### Problem: Import errors in tests
**Solution:**
1. Verify venv is activated
2. Rebuild venv with rebuild script
3. Check for circular imports in pm_app modules

### Problem: Security headers missing
**Solution:**
1. Review configuration in app.py
2. Verify X-Content-Type-Options is set
3. Check CSRF protection is enabled (except in tests)

### Problem: Performance degradation
**Solution:**
1. Run health_check.py
2. Profile database queries
3. Review inline maintenance frequency in app.py
4. Check photo/upload file count (can slow queries)

---

## Key Files to Monitor

- `.env` - Configuration (regenerate SECRET_KEY quarterly)
- `requirements.txt` - Dependencies (check for updates monthly)
- `pytest.ini` - Test configuration
- `tests/conftest.py` - Test fixtures
- `app.py` - Core configuration and routes
- `model.py` - Database schema (migrations needed for changes)

---

## Prevention Tips

1. **Run tests before committing:**
   ```powershell
   .\.venv\Scripts\python.exe -m pytest -v
   ```

2. **Check environment before deploying:**
   ```powershell
   .\.venv\Scripts\python.exe .\health_check.py
   ```

3. **Review security settings monthly:**
   - Verify cookies are Secure/HttpOnly/SameSite
   - Check SECRET_KEY rotation schedule
   - Review authentication logs

4. **Keep dependencies current:**
   - Security updates applied within 24 hours
   - Major updates tested in staging first
   - Pin versions in requirements.txt for reproducibility

---

## Emergency Recovery

If the system becomes unstable:

1. **Isolate the issue:**
   ```powershell
   .\.venv\Scripts\python.exe .\health_check.py
   ```

2. **Rebuild environment:**
   ```powershell
   .\rebuild_venv.bat
   ```

3. **Restore database:**
   - Use most recent backup
   - Never restore SQLite database in production

4. **Verify configuration:**
   - Check `.env` has all required variables
   - Verify DATABASE_URL points to correct server
   - Confirm SECRET_KEY is set and strong

---

**Last Updated:** April 17, 2026  
**Maintenance Owner:** [Your Team]
