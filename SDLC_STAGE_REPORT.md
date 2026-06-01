# SDLC Stage Report (Development, Testing, Staging, Production)

## Scope
This report summarizes an execution-based readiness check across four stages:
1. Development
2. Testing
3. Staging
4. Production

## Stage 1: Development

### Checks run
- Dependency consistency (`pip check`)
- Lint availability/execution (`python -m flake8 app.py pm_app tests`)
- Bytecode compile sanity (`python -m compileall -q app.py pm_app tests`)

### Evidence
- `No broken requirements found.` from `stage_dev_pip_check.txt`
- `No module named flake8` from `stage_dev_flake8.txt`
- Compile status `PASS` from `stage_dev_compile_status.txt`

### Status
- **Conditional pass**

### Findings
- Dependencies are internally consistent.
- Code compiles successfully.
- Lint gate is currently blocked because `flake8` is not installed in the active virtual environment.

## Stage 2: Testing

### Checks run
- Full regression evidence (existing run): `pytest_latest.txt`
- Fresh targeted spot check: `python -m pytest tests/test_auth.py -q --maxfail=1`

### Evidence
- `2 failed, 46 passed, 4 warnings` in `pytest_latest.txt`
- Failures: `tests/test_notifications.py::test_sender_can_delete_own_message` and `tests/test_notifications.py::test_non_sender_cannot_delete_message`
- Fresh run shows teardown instability after test execution:
  - `KeyboardInterrupt`
  - final exception in teardown path: `KeyError` from `_pytest/tmpdir.py` stash handling

### Status
- **Fail**

### Findings
- Functional regressions exist in notification delete-message behavior.
- Test environment/tooling is unstable during teardown, reducing confidence in deterministic CI outcomes.

## Stage 3: Staging

### Checks run
- Flask app smoke checks via test client (programmatic run):
  - `GET /login`
  - `GET /`
  - `GET /this-route-should-not-exist`
  - security header probe (`X-Content-Type-Options`)

### Evidence
- Output: `{"login_status": 200, "root_status": 302, "missing_status": 404, "x_content_type_options_login": "nosniff"}`

### Status
- **Pass**

### Findings
- Core routing behavior is correct (login page reachable, root redirects, missing routes return 404).
- Basic anti-MIME-sniffing response header is present on login route.

## Stage 4: Production

### Checks run
- Configuration probe for production-sensitive cookie and URL scheme settings.

### Evidence
- Output: `{"SESSION_COOKIE_HTTPONLY": true, "SESSION_COOKIE_SECURE": false, "SESSION_COOKIE_SAMESITE": "Lax", "REMEMBER_COOKIE_HTTPONLY": true, "REMEMBER_COOKIE_SECURE": false, "PREFERRED_URL_SCHEME": "http"}` from `stage_prod_config.txt`

### Status
- **Fail (for internet-exposed production)**

### Findings
- Security flags are not production-hardened:
  - `SESSION_COOKIE_SECURE` is false
  - `REMEMBER_COOKIE_SECURE` is false
  - `PREFERRED_URL_SCHEME` is `http`
- This is acceptable only for local/dev environments, not for public production deployment.

## Risk Summary

### High
- Production cookies not marked secure + HTTP preferred URL scheme.

### Medium
- Notification behavior regressions in test suite.

### Medium
- Pytest teardown instability may hide additional defects and cause flaky pipelines.

### Low
- Missing lint package in active env prevents style/static gate from running.

## Recommendation for Release Decision
- **Do not approve production release yet.**

## Mandatory Exit Criteria Before Production
1. Fix notification delete-message regressions and re-run failing tests.
2. Stabilize pytest teardown behavior (investigate fixture/tmp_path/plugin interactions and Python 3.14 compatibility).
3. Enable secure production config defaults or environment overrides:
   - `SESSION_COOKIE_SECURE=true`
   - `REMEMBER_COOKIE_SECURE=true`
   - `PREFERRED_URL_SCHEME=https`
4. Install and enforce lint tooling (`flake8`) in CI/runtime environment.
5. Re-run full test suite and produce a clean pass report.
