#!/usr/bin/env python
"""
System health check script for the PM application.
Runs regular maintenance checks to identify issues that could break the system over time.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from importlib import import_module

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Project root should be the repository root (one level above scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env.prod')
load_dotenv(PROJECT_ROOT / '.env')
VENV_PYTHON = PROJECT_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python.exe"
NULL_DEVICE = "nul" if os.name == "nt" else "/dev/null"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def run_cmd(cmd, description, timeout=30):
    """Run a shell command and print result."""
    print(f"\n{'=' * 60}")
    print(f"[CHECK] {description}")
    print(f"{'=' * 60}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        if result.returncode == 0:
            print("✅ PASS")
            if result.stdout:
                # Show first 500 chars of output
                out = result.stdout.strip()
                if out:
                    print(out[:500])
            return True
        print("❌ FAIL")
        if result.stderr:
            print("Error:", result.stderr[:500])
        return False
    except subprocess.TimeoutExpired:
        print("⏱️ TIMEOUT (exceeded {}s)".format(timeout))
        return False
    except Exception as exc:
        print(f"⚠️ EXCEPTION: {exc}")
        return False


def check_import(module_name, description):
    """Attempt to import a module and report success."""
    print(f"\n{'=' * 60}")
    print(f"[CHECK] {description}")
    print(f"{'=' * 60}")
    try:
        import_module(module_name)
        print("✅ PASS")
        return True
    except ImportError as e:
        print(f"❌ FAIL: {e}")
        return False


def check_file_exists(path, description):
    """Check if a file or directory exists."""
    print(f"\n{'=' * 60}")
    print(f"[CHECK] {description}")
    print(f"{'=' * 60}")
    if path.exists():
        print(f"✅ PASS: {path}")
        return True
    print(f"❌ FAIL: {path} not found")
    return False


def check_env_var(var_name, description):
    """Check if an environment variable is set (non‑empty)."""
    print(f"\n{'=' * 60}")
    print(f"[CHECK] {description}")
    print(f"{'=' * 60}")
    value = os.getenv(var_name)
    if value:
        # Show first few characters (mask sensitive values)
        display = value[:4] + "..." if len(value) > 8 and var_name.lower() in ("secret_key", "password") else value[:50]
        print(f"✅ PASS: {var_name} = {display}")
        return True
    print(f"❌ FAIL: {var_name} not set or empty")
    return False


def check_disk_space(path, min_gb=1):
    """Check available disk space on the given path."""
    print(f"\n{'=' * 60}")
    print(f"[CHECK] Disk space on {path}")
    print(f"{'=' * 60}")
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        if free_gb >= min_gb:
            print(f"✅ PASS: {free_gb:.1f} GB free (minimum {min_gb} GB)")
            return True
        print(f"❌ FAIL: Only {free_gb:.1f} GB free (minimum {min_gb} GB required)")
        return False
    except Exception as e:
        print(f"⚠️ ERROR: {e}")
        return False


def main():
    print("\n" + "=" * 60)
    print("PM APPLICATION - SYSTEM HEALTH CHECK")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = []

    # -----------------------------------------------------------------------
    # 1. Python environment
    # -----------------------------------------------------------------------
    if VENV_PYTHON.exists():
        python_cmd = str(VENV_PYTHON)
    else:
        python_cmd = sys.executable
        print(f"⚠️ Virtual environment not found at {VENV_PYTHON}, using system Python: {python_cmd}")

    results.append(run_cmd(
        f'"{python_cmd}" -c "import sys; print(f\'Python: {{sys.version}}\')"',
        "Python Environment & Version"
    ))

    # -----------------------------------------------------------------------
    # 2. Pip package integrity (list installed packages)
    # -----------------------------------------------------------------------
    results.append(run_cmd(
        f'"{python_cmd}" -m pip list --format=json > {NULL_DEVICE} && echo OK',
        "Pip Package Integrity (list without errors)"
    ))

    # -----------------------------------------------------------------------
    # 3. Core module compilation (syntax check)
    # -----------------------------------------------------------------------
    core_files = ["app.py", "model.py", "pm_app/dashboards/routes.py", "pm_app/auth/routes.py", "pm_app/api/routes.py"]
    existing_files = [f for f in core_files if (PROJECT_ROOT / f).exists()]
    if existing_files:
        results.append(run_cmd(
            f'"{python_cmd}" -m py_compile {" ".join(existing_files)}',
            "Core Module Compilation (syntax check)"
        ))
    else:
        print("⚠️ No core modules found to compile – skipping")
        results.append(False)

    # -----------------------------------------------------------------------
    # 4. Test suite collection (pytest – dry run)
    # -----------------------------------------------------------------------
    results.append(run_cmd(
        f'"{python_cmd}" -m pytest tests/ -q --collect-only --basetemp .pytest_health_tmp > {NULL_DEVICE}',
        "Test Suite Collection (pytest --collect-only)"
    ))

    # -----------------------------------------------------------------------
    # 5. Code linting (flake8) – only if flake8 installed
    # -----------------------------------------------------------------------
    results.append(run_cmd(
        f'"{python_cmd}" -m flake8 --version > {NULL_DEVICE} && '
        f'"{python_cmd}" -m flake8 --jobs 1 app.py pm_app --count',
        "Code Linting (flake8 on app.py and pm_app)"
    ))

    # -----------------------------------------------------------------------
    # 6. Critical environment variables
    # -----------------------------------------------------------------------
    results.append(check_env_var("SECRET_KEY", "SECRET_KEY is set (non‑empty)"))
    results.append(check_env_var("DATABASE_URL", "DATABASE_URL is set (non‑empty)"))
    results.append(check_env_var("APP_ENV", "APP_ENV is set (development/staging/production)"))

    # -----------------------------------------------------------------------
    # 7. Required directories
    # -----------------------------------------------------------------------
    results.append(check_file_exists(PROJECT_ROOT / "uploads", "Uploads directory exists"))
    results.append(check_file_exists(PROJECT_ROOT / "templates", "Templates directory exists"))
    results.append(check_file_exists(PROJECT_ROOT / "static", "Static directory exists"))

    # -----------------------------------------------------------------------
    # 8. Disk space (project root)
    # -----------------------------------------------------------------------
    results.append(check_disk_space(PROJECT_ROOT, min_gb=1))

    # -----------------------------------------------------------------------
    # 9. Import critical Flask extensions (optional)
    # -----------------------------------------------------------------------
    results.append(check_import("flask", "Flask import"))
    results.append(check_import("flask_sqlalchemy", "Flask-SQLAlchemy import"))
    results.append(check_import("flask_login", "Flask-Login import"))
    results.append(check_import("alembic", "Alembic import"))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Checks passed: {passed}/{total}")

    if passed == total:
        print("✅ All checks passed – System is healthy")
        return 0
    else:
        print("⚠️ Some checks failed – Review issues above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
