#!/usr/bin/env python3
"""Deployment and system health audit for the PM/RCA application."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import time
from pathlib import Path
from typing import Any

import redis
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import BootstrapState, User, db
from pm_app import create_app
from pm_app.celery import celery as celery_app
from pm_app.services.bootstrap import initialize_system

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "maintenance" / "reports" / "system_audit.json"


def build_app() -> Any:
    return create_app()


def repair_bootstrap(app: Any) -> dict[str, Any]:
    repair_info = {
        "attempted": False,
        "created_admin": False,
        "bootstrap_complete": None,
        "skipped_reason": None,
        "error": None,
    }

    admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()

    if not admin_email or not admin_password:
        repair_info["skipped_reason"] = "missing_bootstrap_admin_envs"
        return repair_info

    try:
        with app.app_context():
            initialize_system(app)
            repair_info["attempted"] = True
            admin = User.query.filter_by(email=admin_email).first()
            bootstrap_state = BootstrapState.query.first()
            repair_info["created_admin"] = admin is not None and admin.role == "admin"
            repair_info["bootstrap_complete"] = bool(bootstrap_state and bootstrap_state.bootstrap_complete)
    except Exception as exc:
        repair_info["error"] = f"{type(exc).__name__}: {exc}"

    return repair_info


def _is_writable(path: Path) -> bool:
    if not path.exists():
        return False
    return os.access(path, os.W_OK)


def check_routes(app: Any) -> dict[str, Any]:
    results = []
    summary = {"200": 0, "302": 0, "301": 0, "303": 0, "307": 0, "308": 0, "400": 0, "404": 0, "500": 0, "ERROR": 0}

    with app.test_client() as client:
        for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
            methods = sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"})
            for method in methods:
                start = time.perf_counter()
                try:
                    if method == "GET":
                        initial_response = client.get(rule.rule, follow_redirects=False)
                        final_response = client.get(rule.rule, follow_redirects=True)
                    elif method == "POST":
                        initial_response = client.post(rule.rule, follow_redirects=False)
                        final_response = client.post(rule.rule, follow_redirects=True)
                    elif method == "PUT":
                        initial_response = client.put(rule.rule, follow_redirects=False)
                        final_response = client.put(rule.rule, follow_redirects=True)
                    elif method == "DELETE":
                        initial_response = client.delete(rule.rule, follow_redirects=False)
                        final_response = client.delete(rule.rule, follow_redirects=True)
                    else:
                        continue

                    status = initial_response.status_code
                    final_status = final_response.status_code
                    redirect_chain = [
                        {"status": redirect.status_code, "location": redirect.headers.get("Location")}
                        for redirect in final_response.history
                    ]
                    redirect_to = redirect_chain[-1]["location"] if redirect_chain else None
                    if initial_response.status_code in {301, 302, 303, 307, 308}:
                        redirect_to = initial_response.headers.get("Location")
                except Exception as exc:
                    status = "ERROR"
                    final_status = None
                    redirect_chain = []
                    redirect_to = None
                    error = f"{type(exc).__name__}: {exc}"
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

                if status == "ERROR":
                    summary["ERROR"] += 1
                    status_label = "ERROR"
                else:
                    status_label = str(status)
                    summary[str(status)] = summary.get(str(status), 0) + 1

                results.append(
                    {
                        "method": method,
                        "route": rule.rule,
                        "status": status,
                        "final_status": final_status,
                        "redirect_chain": redirect_chain,
                        "redirect_to": redirect_to,
                        "response_time_ms": elapsed_ms,
                        "error": error if status == "ERROR" else None,
                    }
                )

    return {"results": results, "summary": summary}


def check_database(app: Any) -> dict[str, Any]:
    report = {
        "available": False,
        "database_url": app.config.get("SQLALCHEMY_DATABASE_URI"),
        "tables": {},
        "required_tables_present": True,
        "admin_exists": False,
        "bootstrap_complete": False,
        "user_count": 0,
        "roles": [],
        "migration_table_exists": False,
        "migration_revision": None,
        "latest_revision": None,
        "migration_up_to_date": None,
        "error": None,
    }

    try:
        with app.app_context():
            inspector = inspect(db.engine)
            report["available"] = True
            required_tables = [
                "users",
                "bootstrap_state",
                "activities",
                "consumables",
                "messages",
                "form_assignments",
                "user_settings",
                "audit_logs",
            ]
            report["tables"] = {name: inspector.has_table(name) for name in required_tables}
            report["required_tables_present"] = all(report["tables"].values())
            report["admin_exists"] = User.query.filter_by(role="admin").first() is not None
            bootstrap_state = BootstrapState.query.first()
            report["bootstrap_complete"] = bool(bootstrap_state and bootstrap_state.bootstrap_complete)
            report["user_count"] = User.query.count()
            report["roles"] = sorted({row[0] for row in db.session.query(User.role).all()})
            report["migration_table_exists"] = inspector.has_table("alembic_version")
            if report["migration_table_exists"]:
                row = db.session.execute(text("select version_num from alembic_version")).first()
                report["migration_revision"] = row[0] if row else None
            versions = sorted(
                path.stem
                for path in (ROOT / "migrations" / "versions").glob("*.py")
                if path.is_file()
            )
            report["latest_revision"] = versions[-1] if versions else None
            report["migration_up_to_date"] = report["migration_revision"] == report["latest_revision"]
    except OperationalError as exc:
        report["error"] = f"OperationalError: {exc}"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    return report


def check_filesystem(app: Any) -> dict[str, Any]:
    folders = {
        "uploads": Path(app.config.get("UPLOAD_FOLDER", ROOT / "uploads")),
        "photo": Path(app.config.get("PHOTO_LIBRARY_FOLDER", ROOT / "photo")),
        "logs": ROOT / "logs",
        "instance_signatures": ROOT / "instance" / "signatures",
        "maintenance_reports": ROOT / "maintenance" / "reports",
    }

    return {
        name: {
            "exists": path.exists(),
            "is_dir": path.is_dir(),
            "writable": _is_writable(path),
            "path": str(path),
        }
        for name, path in folders.items()
    }


def check_services(app: Any) -> dict[str, Any]:
    redis_url = os.getenv("REDIS_URL") or app.config.get("REDIS_URL") or "redis://localhost:6379/0"
    redis_available = False
    redis_error = None
    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=1.0, socket_connect_timeout=1.0)
        client.ping()
        redis_available = True
    except Exception as exc:
        redis_error = f"{type(exc).__name__}: {exc}"

    smtp_host = os.getenv("ALERT_SMTP_HOST", "").strip()
    smtp_available = None
    smtp_error = None
    if smtp_host:
        smtp_port = int(os.getenv("ALERT_SMTP_PORT", "465"))
        smtp_use_ssl = os.getenv("ALERT_SMTP_USE_SSL", "true").strip().lower() in {"1", "true", "yes", "on"}
        try:
            smtp_client = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=3) if smtp_use_ssl else smtplib.SMTP(smtp_host, smtp_port, timeout=3)
            smtp_client.noop()
            smtp_client.quit()
            smtp_available = True
        except Exception as exc:
            smtp_available = False
            smtp_error = f"{type(exc).__name__}: {exc}"
    else:
        smtp_available = False
        smtp_error = "ALERT_SMTP_HOST is not configured"

    celery_ready = bool(celery_app.conf.broker_url)

    return {
        "redis": {"available": redis_available, "url": redis_url, "error": redis_error},
        "smtp": {"available": smtp_available, "host": smtp_host, "error": smtp_error},
        "celery": {"configured": celery_ready, "broker_url": celery_app.conf.broker_url},
    }


def check_security(app: Any) -> dict[str, Any]:
    secret_key = str(app.config.get("SECRET_KEY") or "")
    secret_ok = bool(secret_key) and len(secret_key) >= 32 and all(marker not in secret_key.lower() for marker in {"test-secret-key", "changeme", "placeholder", "example"})
    debug_disabled = not app.debug
    secure_cookies = bool(app.config.get("SESSION_COOKIE_SECURE"))
    csrf_ready = True
    try:
        from pm_app.csrf import get_csrf_token
        csrf_ready = callable(get_csrf_token)
    except Exception:
        csrf_ready = False

    return {
        "secret_key": {
            "configured": bool(secret_key),
            "strong": secret_ok,
            "value": "***redacted***" if secret_key else None,
        },
        "debug_disabled": debug_disabled,
        "secure_cookies": secure_cookies,
        "csrf_ready": csrf_ready,
    }


def check_environment(app: Any) -> dict[str, Any]:
    app_env = str(app.config.get("APP_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or "development").strip().lower()
    dotenv_present = (ROOT / ".env").exists()
    database_url = app.config.get("SQLALCHEMY_DATABASE_URI")
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
    return {
        "app_env": app_env,
        "dotenv_present": dotenv_present,
        "database_url_configured": bool(database_url),
        "public_base_url_configured": bool(public_base_url) or app_env != "production",
        "debug_disabled": not app.debug,
        "session_cookie_secure": bool(app.config.get("SESSION_COOKIE_SECURE")),
    }


def summarize(route_result: dict[str, Any], db_result: dict[str, Any], fs_result: dict[str, Any], service_result: dict[str, Any], security_result: dict[str, Any], environment_result: dict[str, Any], repair_info: dict[str, Any] | None = None) -> dict[str, Any]:
    critical_failures = []
    warnings = []

    if route_result["summary"].get("ERROR", 0):
        critical_failures.append("route_scan_errors")
    if route_result["summary"].get("500", 0):
        critical_failures.append("route_5xx")
    if not db_result["available"]:
        critical_failures.append("database_unavailable")
    if not db_result["required_tables_present"]:
        critical_failures.append("missing_required_tables")
    if not fs_result["uploads"]["exists"] or not fs_result["uploads"]["writable"]:
        critical_failures.append("uploads_not_ready")
    if not fs_result["logs"]["exists"] or not fs_result["logs"]["writable"]:
        critical_failures.append("logs_not_ready")
    if not security_result["secret_key"]["strong"]:
        critical_failures.append("weak_secret_key")

    if not db_result["admin_exists"]:
        warnings.append("missing_admin_account")
    if db_result["migration_up_to_date"] is False:
        warnings.append("migration_out_of_date")
    if not service_result["redis"]["available"]:
        warnings.append("redis_unavailable")
    if not service_result["smtp"]["available"]:
        warnings.append("smtp_unavailable")
    if not security_result["debug_disabled"] and environment_result["app_env"] == "production":
        warnings.append("debug_enabled")
    if not security_result["secure_cookies"] and environment_result["app_env"] == "production":
        warnings.append("secure_cookies_disabled")
    if not environment_result["dotenv_present"]:
        warnings.append("missing_dotenv")

    status = "PASS" if not critical_failures else "FAIL"
    return {
        "status": status,
        "critical_failures": critical_failures,
        "warnings": warnings,
        "repair": repair_info,
        "route_summary": route_result["summary"],
        "db_summary": db_result,
        "filesystem_summary": fs_result,
        "service_summary": service_result,
        "security_summary": security_result,
        "environment_summary": environment_result,
    }


def print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, indent=2, sort_keys=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deployment and system health checks.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output only.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Where to write JSON output.")
    parser.add_argument("--repair", action="store_true", help="Attempt bootstrap repair when admin bootstrap env vars are configured.")
    args = parser.parse_args()

    app = build_app()
    route_result = check_routes(app)
    db_result = check_database(app)
    fs_result = check_filesystem(app)
    service_result = check_services(app)
    security_result = check_security(app)
    environment_result = check_environment(app)

    repair_info = None
    if args.repair or (not db_result["admin_exists"] and os.getenv("BOOTSTRAP_ADMIN_EMAIL") and os.getenv("BOOTSTRAP_ADMIN_PASSWORD")):
        repair_info = repair_bootstrap(app)
        db_result = check_database(app)

    summary = summarize(route_result, db_result, fs_result, service_result, security_result, environment_result, repair_info)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_report(summary)

    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
