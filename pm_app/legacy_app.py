#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PM/RCA System – Production Ready
All original functionality + dashboard routes module + critical fixes.
"""
# flake8: noqa

import os
import io
import shutil
import uuid
import base64
import secrets
import click
import logging
import re
import json
import mimetypes
import time as _time
import psutil
from urllib.parse import urlparse
from functools import wraps
from datetime import datetime, timedelta, timezone
from typing import Union, Tuple
from xml.sax.saxutils import escape
from flask import Flask, render_template, redirect, url_for, abort, request, flash, jsonify, send_file, send_from_directory, session, has_request_context, current_app, has_app_context, g
from werkzeug.wrappers import Response
from flask_migrate import Migrate
from flask_login import login_required, current_user
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, func, or_, inspect, text
from sqlalchemy.pool import QueuePool
from dotenv import load_dotenv
from alert_system import send_alert

# Local modules
from model import db, Consumable, Activity, User, Message, UserSettings, FormAssignment, AuditLog, AccountActivationToken, PasswordResetToken, BootstrapState
from services.login_throttle import LoginThrottleStore
from pm_app.dashboards.routes import register_dashboard_routes
from pm_app.auth.routes import register_auth_routes
from pm_app.api.routes import register_api_routes
from pm_app.admin.routes import register_admin_routes
from pm_app.content.routes import register_content_routes
from pm_app.setup_routes import register_setup_routes
from pm_app.legacy_analysis import analyze_uploaded_photo_quality, build_review_priority, classify_risk_level, compute_activity_stage_durations, format_duration_seconds, derive_sla_suggestion, extract_recommendations_from_details, extract_risk_score_from_details, extract_sla_deadline_from_details, detect_snags_from_form, summarize_snag_profile, analyze_outage_signals, extract_detected_snags_from_details, build_activity_suggestion_with_source
from pm_app.legacy_parsing import parse_activity_kv, parse_activity_details_structured
from pm_app.legacy_pdf import parse_float_value, extract_metric_from_details
from pm_app.desk.routes import register_desk_routes
from pm_app.services.observability import configure_request_observability
from pm_app.services.maintenance import MaintenanceService
from pm_app.services.email import send_activation_email, send_password_reset_email
from pm_app.services.bootstrap import initialize_system, _bootstrap_is_disabled
from app_pkg.utils import *  # noqa: F403

# Optional imports
try:
    from PIL import Image
    # HEIC support  
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    Image = None
from reportlab.graphics import renderPM, renderSVG
from reportlab.graphics.barcode import qr as reportlab_qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from openpyxl import Workbook
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import redis

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# ============================
# CONFIGURATION
# ============================
APP_BUILD_ID = os.environ.get("APP_BUILD_ID", "unknown")

# ============================
# LOGGING SETUP (PUT HERE)
# ============================

from pm_app.legacy_helpers import *
from pm_app.legacy_helpers import (
    _INLINE_MAINTENANCE_MIN_INTERVAL_SECONDS,
    _SLA_DUE_SOON_ALERT_COOLDOWN_HOURS,
    _SLA_OVERDUE_ESCALATION_COOLDOWN_HOURS,
    _check_image_magic,
    _is_valid_image_file_path,
)

def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log_redis_unavailable(logger, app_env):
    if app_env == "production":
        logger.exception("Redis unavailable. Falling back to in-memory throttling.")
    else:
        logger.warning("Redis unavailable. Falling back to in-memory throttling.")


def _latest_migration_revision():
    migration_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations", "versions")
    revisions = []
    if os.path.isdir(migration_dir):
        for filename in os.listdir(migration_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                revisions.append(filename[:-3])
    return sorted(revisions)[-1] if revisions else None


def _writable_directory(path):
    return bool(path) and os.path.exists(path) and os.access(path, os.W_OK)


def _collect_startup_integrity(app):
    integrity = {
        "blocking_failures": [],
        "warnings": [],
        "bootstrap_complete": False,
        "admin_exists": False,
        "user_count": 0,
        "migration_out_of_date": False,
        "current_revision": None,
        "latest_revision": _latest_migration_revision(),
        "redis_available": bool(app.config.get("REDIS_CLIENT")),
        "uploads_writable": _writable_directory(app.config.get("UPLOAD_FOLDER")),
        "logs_writable": _writable_directory(os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")),
    }

    try:
        with app.app_context():
            inspector = inspect(db.engine)
            integrity["bootstrap_complete"] = bool(BootstrapState.query.first() and BootstrapState.query.first().bootstrap_complete)
            integrity["admin_exists"] = User.query.filter(User.role.in_(["admin", "developer"])).first() is not None
            integrity["user_count"] = User.query.count()
            if inspector.has_table("alembic_version"):
                row = db.session.execute(text("select version_num from alembic_version")).first()
                integrity["current_revision"] = row[0] if row else None
            integrity["migration_out_of_date"] = integrity["current_revision"] != integrity["latest_revision"]
    except Exception as exc:
        integrity["blocking_failures"].append(f"database_unavailable:{type(exc).__name__}:{exc}")
        return integrity

    if not integrity["bootstrap_complete"] or not integrity["admin_exists"]:
        integrity["blocking_failures"].append("missing_admin_account")

    if not integrity["uploads_writable"]:
        integrity["blocking_failures"].append("uploads_not_ready")

    if not integrity["logs_writable"]:
        integrity["blocking_failures"].append("logs_not_ready")

    if integrity["migration_out_of_date"]:
        integrity["warnings"].append("migration_out_of_date")

    if not integrity["redis_available"]:
        integrity["warnings"].append("redis_unavailable")

    if app.config.get("APP_ENV") == "production":
        if integrity["migration_out_of_date"]:
            integrity["blocking_failures"].append("migration_out_of_date")

    return integrity


def _collect_audit_history(app, window_hours=24, limit=10):
    cutoff = utcnow_naive() - timedelta(hours=window_hours)
    try:
        with app.app_context():
            query = AuditLog.query.filter(AuditLog.created_at >= cutoff).order_by(AuditLog.created_at.desc())
            total_events = query.count()
            recent_events = [entry.to_dict() for entry in query.limit(limit).all()]
        return {
            "window_hours": window_hours,
            "total_events": total_events,
            "recent_events": recent_events,
        }
    except Exception:
        return {
            "window_hours": window_hours,
            "total_events": 0,
            "recent_events": [],
        }


def _enforce_startup_integrity(app):
    integrity = _collect_startup_integrity(app)
    if app.config.get("APP_ENV") == "production" and integrity["blocking_failures"]:
        raise RuntimeError(
            "Critical system integrity failure:\n- " + "\n- ".join(integrity["blocking_failures"])
        )
    if integrity["blocking_failures"] and app.config.get("APP_ENV") != "production":
        app.logger.warning("Startup integrity warnings: %s", ", ".join(integrity["blocking_failures"]))


def _compute_live_dashboard_counts(db, Activity, User, Consumable, current_user, is_technician_role, get_public_holidays, high_risk_threshold):
    technician_emails_query = db.session.query(User.email).filter(User.role == "technician")
    current_user_is_authenticated = bool(getattr(current_user, "is_authenticated", False))
    current_user_email = getattr(current_user, "email", None)
    current_user_role = getattr(current_user, "role", "")

    def safe(fn, name=None):
        try:
            return fn()
        except Exception:
            current_app.logger.exception("safe() failed for %s", name or getattr(fn, '__name__', '<callable>'))
            return 0

    field_submission_base = Activity.query.filter(
        Activity.activity_type.in_(["pm", "rca"]),
        Activity.created_by.in_(technician_emails_query),
    )
    pending_base = field_submission_base.filter(Activity.approved_at.is_(None))
    now = utcnow_naive()
    high_risk_pending_count = pending_base.filter(Activity.risk_score >= high_risk_threshold).count()
    sla_overdue_count = pending_base.filter(
        Activity.sla_deadline.is_not(None),
        Activity.sla_deadline < now,
    ).count()

    counts = {
        "users_total": safe(lambda: db.session.query(db.func.count(User.id)).scalar() or 0, name='users_total'),
        "blocked_users": safe(lambda: db.session.query(db.func.count(User.id)).filter(User.is_blocked.is_(True)).scalar() or 0, name='blocked_users'),
        "technician_users": safe(lambda: db.session.query(db.func.count(User.id)).filter(User.role == "technician").scalar() or 0, name='technician_users'),
        "staff_users": safe(lambda: db.session.query(db.func.count(User.id)).filter(User.role == "staff").scalar() or 0, name='staff_users'),
        "manager_users": safe(lambda: db.session.query(db.func.count(User.id)).filter(User.role == "manager").scalar() or 0, name='manager_users'),
        "general_manager_users": safe(lambda: db.session.query(db.func.count(User.id)).filter(User.role == "general_manager").scalar() or 0, name='general_manager_users'),
        "consumables_count": safe(lambda: db.session.query(db.func.count(Consumable.id)).scalar() or 0, name='consumables_count'),
        "total_rcas": safe(lambda: db.session.query(db.func.count(Activity.id)).filter(Activity.activity_type == "rca").scalar() or 0, name='total_rcas'),
        "total_snags": safe(lambda: db.session.query(db.func.count(Activity.id)).filter(Activity.activity_type == "snag").scalar() or 0, name='total_snags'),
        "total_dars": safe(lambda: db.session.query(db.func.count(Activity.id)).filter(Activity.activity_type == "dar").scalar() or 0, name='total_dars'),
        "total_pms": safe(lambda: db.session.query(db.func.count(Activity.id)).filter(Activity.activity_type == "pm").scalar() or 0, name='total_pms'),
        "pending_pm_rcas": safe(lambda: field_submission_base.filter(Activity.approved_at.is_(None)).count(), name='pending_pm_rcas'),
        "high_risk_pending_pm_rcas": safe(lambda: high_risk_pending_count, name='high_risk_pending_pm_rcas'),
        "sla_overdue_pm_rcas": safe(lambda: sla_overdue_count, name='sla_overdue_pm_rcas'),
        "approved_pm_forms": safe(lambda: field_submission_base.filter(Activity.is_approved.is_(True)).count(), name='approved_pm_forms'),
        "rejected_pm_rcas": safe(lambda: field_submission_base.filter(
            Activity.is_approved.is_(False),
            Activity.approved_at.is_not(None),
        ).count(), name='rejected_pm_rcas'),
        "holiday_entries": safe(lambda: len(get_public_holidays()), name='holiday_entries'),
        "notification_count": 0,
    }
    counts["field_total_forms"] = counts["pending_pm_rcas"] + counts["approved_pm_forms"] + counts["rejected_pm_rcas"]
    counts.setdefault("technician_pm", 0)
    counts.setdefault("technician_rca", 0)
    counts.setdefault("technician_consumables", 0)
    counts.setdefault("technician_total", 0)
    counts.setdefault("technician_rejected", 0)

    if current_user_is_authenticated and is_technician_role(current_user_role):
        try:
            technician_pm = Activity.query.filter_by(activity_type="pm", created_by=current_user_email).count()
            technician_rca = Activity.query.filter_by(activity_type="rca", created_by=current_user_email).count()
            technician_consumables = Consumable.query.filter_by(created_by=current_user_email).count()
            technician_rejected = Activity.query.filter(
                Activity.activity_type.in_(["pm", "rca"]),
                Activity.created_by == current_user_email,
                Activity.is_approved.is_(False),
                Activity.approved_at.is_not(None),
            ).count()
            counts["technician_pm"] = technician_pm
            counts["technician_rca"] = technician_rca
            counts["technician_consumables"] = technician_consumables
            counts["technician_total"] = technician_pm + technician_rca + technician_consumables
            counts["technician_rejected"] = technician_rejected
        except Exception:
            current_app.logger.exception("Failed to compute per-technician counts")

    return counts


def _create_live_dashboard_counts_provider(app, db, Activity, User, Consumable, get_public_holidays, normalize_role, is_technician_role):
    cache = {"key": None, "expires_at": 0.0, "payload": None}

    def get_live_dashboard_counts():
        ttl_seconds = float(app.config.get("LIVE_DASHBOARD_COUNTS_CACHE_TTL_SECONDS", 35))
        current_key = (
            bool(getattr(current_user, "is_authenticated", False)),
            getattr(current_user, "email", None),
            normalize_role(getattr(current_user, "role", "")),
        )
        now = _time.monotonic()

        if cache["payload"] is not None and cache["key"] == current_key and now < cache["expires_at"]:
            return cache["payload"]

        payload = _compute_live_dashboard_counts(
            db,
            Activity,
            User,
            Consumable,
            current_user,
            is_technician_role,
            get_public_holidays,
            HIGH_RISK_THRESHOLD,
        )
        cache["key"] = current_key
        cache["expires_at"] = now + ttl_seconds
        cache["payload"] = payload
        return payload

    return get_live_dashboard_counts


def create_app(test_config=None):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    app = Flask(__name__, root_path=root_dir, template_folder="templates", static_folder="static")
    # Ensure WebP images are served with correct MIME type
    mimetypes.add_type('image/webp', '.webp')

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "images/soliton-telmec.jpeg", mimetype="image/jpeg")

    # Use absolute base directory for robust path handling
    BASE_DIR = root_dir

    # Ensure instance directory exists
    instance_dir = os.path.join(BASE_DIR, "instance")
    os.makedirs(instance_dir, exist_ok=True)

    test_config = dict(test_config or {})
    is_testing = bool(test_config.get("TESTING"))

    dotenv_path = os.path.join(BASE_DIR, ".env")
    current_env = str(test_config.get("APP_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    if current_env != "production":
        load_dotenv(dotenv_path)

    def _config_value(name, default=None):
        return test_config.get(name, os.getenv(name, default))

    def _config_bool(name, default=False):
        raw_value = _config_value(name, "1" if default else "0")
        if isinstance(raw_value, bool):
            return raw_value
        return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}

    def _config_int(name, default):
        return int(_config_value(name, str(default)))

    def _collect_public_base_url_errors():
        public_url = str(_config_value("PUBLIC_BASE_URL", "") or "").strip()
        errors = []
        if not public_url:
            errors.append("PUBLIC_BASE_URL is required in production. Set it to your public HTTPS URL.")
            return errors
        if "//" not in public_url:
            public_url = f"https://{public_url}"
        parsed = urlparse(public_url)
        host = (parsed.netloc or "").lower()
        invalid_hosts = {"localhost", "127.0.0.1", "::1", "your-production-domain.example", "example.com", "example.org", "example.net"}
        if parsed.scheme != "https":
            errors.append("Production requires PUBLIC_BASE_URL to use https.")
        if not host or host in invalid_hosts or host.endswith(".example"):
            errors.append("Production requires PUBLIC_BASE_URL to be a real public HTTPS hostname, not a placeholder or localhost value.")
        return errors

    def _collect_production_errors(database_url, secret_key, secure_cookies):
        errors = []
        if not database_url:
            errors.append(
                "DATABASE_URL is required in production. Configure a PostgreSQL URL, for example: "
                "postgresql+psycopg://postgres:password@localhost:5432/pm_db"
            )
        elif not database_url.startswith("postgresql+psycopg://"):
            errors.append(
                "Production requires PostgreSQL with psycopg. Set DATABASE_URL to "
                "postgresql+psycopg://..."
            )
        if not secret_key:
            errors.append(
                "SECRET_KEY is required. Set a strong random value in .env, e.g.: "
                "SECRET_KEY=" + secrets.token_hex(32)
            )
        else:
            lowered_secret = secret_key.lower()
            weak_secret_markers = (
                "change-me",
                "changeme",
                "dev-secret",
                "test-secret",
                "placeholder",
                "example",
            )
            if len(secret_key) < 32 or any(marker in lowered_secret for marker in weak_secret_markers):
                errors.append(
                    "Production requires a strong SECRET_KEY. Use a random value such as: "
                    "SECRET_KEY=" + secrets.token_hex(32)
                )
        errors.extend(_collect_public_base_url_errors())
        if not secure_cookies:
            errors.append(
                "Production requires secure cookies. Set SESSION_COOKIE_SECURE=1 in the environment and deploy behind TLS."
            )
        return errors

    def _validate_production_runtime_dependencies(database_url, redis_url, smtp_host, smtp_port, smtp_use_ssl, smtp_use_tls):
        errors = []
        if database_url.startswith("postgresql+psycopg://"):
            try:
                engine = create_engine(
                    database_url,
                    pool_pre_ping=True,
                    connect_args={"connect_timeout": 1},
                )
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            except Exception as exc:
                errors.append(f"Database reachability check failed: {exc}")
        if redis_url:
            try:
                redis_client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                if not redis_client.ping():
                    errors.append("Redis reachability check failed: ping returned false")
            except Exception as exc:
                errors.append(f"Redis reachability check failed: {exc}")
        if smtp_host:
            try:
                if smtp_use_ssl:
                    smtp_client = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=5)
                else:
                    smtp_client = smtplib.SMTP(smtp_host, smtp_port, timeout=5)
                    if smtp_use_tls:
                        smtp_client.starttls()
                smtp_client.quit()
            except Exception as exc:
                errors.append(f"SMTP reachability check failed: {exc}")
        return errors

    app_env = str(test_config.get("APP_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or "development").strip().lower()
    if app_env not in {"development", "staging", "production"}:
        app_env = "development"

    def _resolve_sqlite_database_url(database_url):
        if not database_url.startswith("sqlite"):
            return database_url
        parsed = urlparse(database_url)
        if parsed.scheme != "sqlite":
            return database_url

        raw_path = parsed.path.lstrip("/")
        if not raw_path:
            return database_url

        # Already absolute (Windows drive path or Unix absolute path)?
        if os.path.isabs(raw_path) or (len(raw_path) >= 2 and raw_path[1] == ":"):
            return database_url

        absolute_path = os.path.abspath(os.path.join(BASE_DIR, raw_path))
        normalized_path = absolute_path.replace(os.sep, "/")
        return f"sqlite:///{normalized_path}"

    database_url = (test_config.get("SQLALCHEMY_DATABASE_URI") or os.getenv("DATABASE_URL") or "").strip()
    dev_database_url = (test_config.get("DEV_DATABASE_URL") or os.getenv("DEV_DATABASE_URL") or "").strip()
    if not database_url:
        if is_testing:
            db_path = os.path.join(BASE_DIR, "instance", "test_pm.sqlite")
            database_url = f"sqlite:///{db_path}"
        elif app_env in {"development", "staging"}:
            if dev_database_url:
                database_url = dev_database_url
            else:
                db_path = os.path.join(BASE_DIR, "instance", "dev_pm.sqlite")
                database_url = f"sqlite:///{db_path}"
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if (
        database_url.startswith("postgresql://")
        and "+psycopg" not in database_url
        and "+psycopg2" not in database_url
    ):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    database_url = _resolve_sqlite_database_url(database_url)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Whether managers are allowed to approve/reject forms (developer toggle)
    app.config.setdefault("MANAGER_CAN_APPROVE", False)
    # Use different engine options for SQLite vs other backends. Passing
    # pool-size related kwargs to SQLite's StaticPool/NullPool can raise
    # TypeError; keep SQLite engine options minimal.
    if database_url.startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"check_same_thread": False}}
    else:
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "poolclass": QueuePool,
            "pool_size": 20,
            "max_overflow": 30,
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "pool_timeout": 30,
            "connect_args": {"connect_timeout": 1},
            "echo": False,  # Set to True for SQL query logging
        }
    secret_key = (test_config.get("SECRET_KEY") or os.getenv("SECRET_KEY") or "").strip()
    if not secret_key:
        if is_testing:
            secret_key = "test-secret-key"
    secure_cookie_default = app_env == "production"
    _secure_cookies = _config_bool("SESSION_COOKIE_SECURE", default=secure_cookie_default)
    if not is_testing and app_env == "production":
        production_errors = _collect_production_errors(database_url, secret_key, _secure_cookies)
        if production_errors:
            raise RuntimeError("Production configuration errors:\n- " + "\n- ".join(production_errors))
    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = _config_bool("SESSION_COOKIE_HTTPONLY", default=True)
    app.config["SESSION_COOKIE_SAMESITE"] = str(
        _config_value("SESSION_COOKIE_SAMESITE", "Lax") or "Lax"
    )
    app.config["SESSION_COOKIE_SECURE"] = _secure_cookies
    app.config["REMEMBER_COOKIE_HTTPONLY"] = _config_bool("REMEMBER_COOKIE_HTTPONLY", default=True)
    app.config["REMEMBER_COOKIE_SAMESITE"] = str(
        _config_value("REMEMBER_COOKIE_SAMESITE", "Lax") or "Lax"
    )
    app.config["REMEMBER_COOKIE_SECURE"] = _secure_cookies
    preferred_url_scheme = str(
        _config_value("PREFERRED_URL_SCHEME", "https" if _secure_cookies else "http")
    ).strip()
    if _secure_cookies and preferred_url_scheme == "http":
        preferred_url_scheme = "https"
    app.config["PREFERRED_URL_SCHEME"] = preferred_url_scheme
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

    app.config["UPLOAD_FOLDER"] = os.path.join(os.path.abspath(os.path.dirname(__file__)), "uploads")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.config["PHOTO_LIBRARY_FOLDER"] = os.path.join(os.path.abspath(os.path.dirname(__file__)), "photo")
    os.makedirs(app.config["PHOTO_LIBRARY_FOLDER"], exist_ok=True)
    app.config["MONITORED_IMAGE_FOLDERS"] = {
        "uploads": app.config["UPLOAD_FOLDER"],
        "photo": app.config["PHOTO_LIBRARY_FOLDER"],
    }
    app.config["PHOTO_LIBRARY_CONTROLS"] = normalize_photo_library_controls(DEFAULT_PHOTO_LIBRARY_CONTROLS)
    max_photo_mb = max(1, min(50, _config_int("MAX_PHOTO_MB", 10)))
    max_upload_default_mb = max(256, len(TECHNICIAN_PHOTO_FIELDS) * max_photo_mb + 16)
    max_upload_mb = max(
        max_upload_default_mb,
        max(64, min(4096, _config_int("MAX_UPLOAD_MB", max_upload_default_mb))),
    )
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024
    app.config["MAX_PHOTO_MB"] = max_photo_mb
    app.config["MAX_PHOTO_BYTES"] = max_photo_mb * 1024 * 1024
    app.config["ROLE_ACCESS_MATRIX"] = normalize_role_access_matrix(DEFAULT_ROLE_ACCESS_MATRIX)
    app.config["SUPPORTED_LANGUAGES"] = SUPPORTED_LANGUAGES
    app.config["SETTINGS_TRANSLATIONS"] = SETTINGS_TRANSLATIONS
    app.config["ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif", "webp"}
    app.config["PASSWORD_HASH_METHOD"] = str(
        test_config.get("PASSWORD_HASH_METHOD", os.getenv("PASSWORD_HASH_METHOD", "pbkdf2:sha256:150000"))
    ).strip()
    app.config["SLA_STANDARD_HOURS"] = _config_int("SLA_STANDARD_HOURS", SLA_HOURS_STANDARD)
    app.config["SLA_CRITICAL_HOURS"] = _config_int("SLA_CRITICAL_HOURS", SLA_HOURS_CRITICAL)
    app.config["SLA_DUE_SOON_HOURS"] = _config_int("SLA_DUE_SOON_HOURS", SLA_DUE_SOON_HOURS)
    # Controls overdue escalation emails; due-soon review reminders are always sent.
    app.config["SLA_ESCALATION_ENABLED"] = _config_bool("SLA_ESCALATION_ENABLED", default=True)

    app.config["S3_BUCKET"] = _config_value("S3_BUCKET")
    app.config["S3_KEY"] = _config_value("S3_KEY")
    app.config["S3_SECRET"] = _config_value("S3_SECRET")
    app.config["S3_REGION"] = _config_value("S3_REGION", "us-east-1")
    app.config["APP_ENV"] = app_env
    app.config["TESTING"] = is_testing
    app.config["SEED_SAMPLE_DATA"] = not is_testing

    # Security: Disable self-service developer registration in production by default
    # Set SELF_SERVICE_ENABLED=true in .env ONLY if you want public registration enabled
    self_service_enabled = _config_bool("SELF_SERVICE_ENABLED", default=(not is_testing and app_env in {"development", "staging"}))
    app.config["SELF_SERVICE_ENABLED"] = self_service_enabled

    # Optional IP whitelist for self-service endpoint (comma-separated CIDR blocks)
    # Leave empty to allow all (when SELF_SERVICE_ENABLED=true)
    allowed_ips = _config_value("SELF_SERVICE_ALLOWED_IPS", "").strip()
    if allowed_ips:
        import ipaddress
        app.config["SELF_SERVICE_ALLOWED_IPS"] = [
            ipaddress.ip_network(cidr.strip(), strict=False)
            for cidr in allowed_ips.split(",")
            if cidr.strip()
        ]
    else:
        app.config["SELF_SERVICE_ALLOWED_IPS"] = []

    setup_logging(app)

    inline_automation_default = "1" if (is_testing or app_env != "production") else "0"
    access_log_default = "1" if (not is_testing and app_env in {"staging", "production"}) else "0"
    app.config["ENABLE_INLINE_AUTOMATIONS"] = str(
        _config_value("ENABLE_INLINE_AUTOMATIONS", inline_automation_default)
    ).strip() == "1"
    app.config["INLINE_MAINTENANCE_MIN_INTERVAL_SECONDS"] = max(
        30,
        _config_int("INLINE_MAINTENANCE_MIN_INTERVAL_SECONDS", _INLINE_MAINTENANCE_MIN_INTERVAL_SECONDS),
    )
    app.config["ACCESS_LOG_ENABLED"] = str(
        _config_value("ACCESS_LOG_ENABLED", access_log_default)
    ).strip() == "1"

    if test_config:
        override_config = dict(test_config)
        for bool_key in ("SESSION_COOKIE_SECURE", "REMEMBER_COOKIE_SECURE"):
            if bool_key in override_config:
                override_config[bool_key] = str(override_config[bool_key]).strip().lower() in {"1", "true", "yes", "on"}
        app.config.update(override_config)

    app.config["RESET_DEV_DB_ON_START"] = _config_bool(
        "RESET_DEV_DB_ON_START",
        default=False,
    )

    def _reset_local_dev_database():
        if _bootstrap_is_disabled():
            return
        if app.config.get("TESTING"):
            return
        if app.config.get("APP_ENV") not in {"development", "staging"}:
            return
        if not str(app.config.get("SQLALCHEMY_DATABASE_URI", "")).startswith("sqlite"):
            return
        if not app.config.get("RESET_DEV_DB_ON_START"):
            return

        upload_folder = app.config.get("UPLOAD_FOLDER")
        if upload_folder and os.path.isdir(upload_folder):
            for entry in os.listdir(upload_folder):
                entry_path = os.path.join(upload_folder, entry)
                try:
                    if os.path.isdir(entry_path) and not os.path.islink(entry_path):
                        shutil.rmtree(entry_path)
                    else:
                        os.unlink(entry_path)
                except FileNotFoundError:
                    continue

        signatures_dir = os.path.join(BASE_DIR, "instance", "signatures")
        if os.path.isdir(signatures_dir):
            shutil.rmtree(signatures_dir)

        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            db.session.add(BootstrapState(bootstrap_complete=False))
            db.session.commit()

    log_level_name = str(_config_value("LOG_LEVEL", "INFO")).upper()
    app.logger.setLevel(getattr(logging, log_level_name, logging.INFO))

    run_runtime_validation = not bool(test_config) and app_env == "production"
    if not bool(test_config):
        run_runtime_validation = True
    else:
        run_runtime_validation = _config_bool("RUN_RUNTIME_VALIDATION", default=False)

    if not is_testing and app_env == "production" and run_runtime_validation:
        smtp_host = str(_config_value("ALERT_SMTP_HOST", "") or "").strip()
        smtp_port = int(_config_value("ALERT_SMTP_PORT", "465"))
        smtp_use_ssl = _config_bool("ALERT_SMTP_USE_SSL", default=True)
        smtp_use_tls = _config_bool("ALERT_SMTP_USE_TLS", default=False)
        runtime_errors = _validate_production_runtime_dependencies(
            database_url,
            str(_config_value("REDIS_URL", "") or "").strip(),
            smtp_host,
            smtp_port,
            smtp_use_ssl,
            smtp_use_tls,
        )
        if runtime_errors:
            raise RuntimeError("Production runtime validation errors:\n- " + "\n- ".join(runtime_errors))

    redis_client = None
    redis_url = str(_config_value("REDIS_URL", "redis://localhost:6379/0") or "redis://localhost:6379/0").strip()
    if redis_url and not is_testing:
        try:
            redis_client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5)
            redis_client.ping()
        except Exception:
            _log_redis_unavailable(app.logger, app_env)
            redis_client = None
    app.config["REDIS_CLIENT"] = redis_client

    max_login_attempts = _config_int("MAX_LOGIN_ATTEMPTS", 5)
    login_window_seconds = _config_int("LOGIN_WINDOW_SECONDS", 15 * 60)
    login_lockout_seconds = _config_int("LOGIN_LOCKOUT_SECONDS", 15 * 60)
    login_throttle_store = LoginThrottleStore(
        max_attempts=max_login_attempts,
        window_seconds=login_window_seconds,
        lockout_seconds=login_lockout_seconds,
        redis_client=redis_client,
    )

    def hash_password(plain_text):
        hash_method = (app.config.get("PASSWORD_HASH_METHOD") or "pbkdf2:sha256:260000").strip()
        return generate_password_hash(plain_text, method=hash_method)

    def get_avatar_choice_map(users):
        user_ids = [user.id for user in users if getattr(user, "id", None) is not None]
        if not user_ids:
            return {}
        settings_rows = UserSettings.query.filter(UserSettings.user_id.in_(user_ids)).all()
        by_user_id = {}
        for row in settings_rows:
            prefs = row.get_preferences()
            avatar_key = prefs.get("profile_avatar") if isinstance(prefs, dict) else None
            by_user_id[row.user_id] = resolve_avatar_key(avatar_key, None)
        resolved = {}
        for user in users:
            resolved[user.id] = resolve_avatar_key(by_user_id.get(user.id), user.gender)
        return resolved

    db.init_app(app)
    _reset_local_dev_database()
    Migrate(app, db)

    with app.app_context():
        initialize_system(app)
        if os.getenv("FORCE_DB_STARTUP_CHECK", "0") == "1" or (is_testing and app_env == "production"):
            _enforce_startup_integrity(app)

        # Optional startup DB checks: by default skip to avoid blocking app creation
        # during tests or environments where DB is not available. Set
        # `FORCE_DB_STARTUP_CHECK=1` in the environment to enable the checks.
        try:
            if os.getenv("FORCE_DB_STARTUP_CHECK", "0") == "1":
                if not inspect(db.engine).has_table("user_settings"):
                    raise RuntimeError("user_settings table not initialized yet")
                latest_developer_settings = (
                    db.session.query(UserSettings)
                    .join(User, UserSettings.user_id == User.id)
                    .filter(User.role == "developer")
                    .order_by(UserSettings.updated_at.desc())
                    .first()
                )
                if latest_developer_settings:
                    preferences = latest_developer_settings.get_preferences()
                    stored_limits = preferences.get("system_upload_limits") if isinstance(preferences, dict) else None
                    if isinstance(stored_limits, dict):
                        stored_photo_mb = int(stored_limits.get("max_photo_mb", app.config["MAX_PHOTO_MB"]))
                        stored_upload_mb = int(
                            stored_limits.get(
                                "max_upload_mb",
                                max(1, int(app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024))),
                            )
                        )
                        min_total_mb = max(16, len(TECHNICIAN_PHOTO_FIELDS) * max(1, stored_photo_mb))
                        if 1 <= stored_photo_mb <= 50 and min_total_mb <= stored_upload_mb <= 4096:
                            app.config["MAX_PHOTO_MB"] = stored_photo_mb
                            app.config["MAX_PHOTO_BYTES"] = stored_photo_mb * 1024 * 1024
                            app.config["MAX_CONTENT_LENGTH"] = stored_upload_mb * 1024 * 1024
                    stored_role_matrix = preferences.get("system_role_access_matrix") if isinstance(preferences, dict) else None
                    if isinstance(stored_role_matrix, dict):
                        app.config["ROLE_ACCESS_MATRIX"] = normalize_role_access_matrix(stored_role_matrix)
                    stored_photo_controls = preferences.get("system_photo_library_controls") if isinstance(preferences, dict) else None
                    if isinstance(stored_photo_controls, dict):
                        app.config["PHOTO_LIBRARY_CONTROLS"] = normalize_photo_library_controls(stored_photo_controls)
        except RuntimeError:
            pass
        except Exception as exc:
            app.logger.warning("Could not load persisted developer upload limits: %s", exc)

    # Initialize observability + shared extensions
    configure_request_observability(app, access_log_enabled=app.config.get("ACCESS_LOG_ENABLED", False))
    from pm_app.extensions import init_extensions
    extensions = init_extensions(app, redis_client=redis_client)
    # Expose commonly used extension instances in local scope for backward compatibility
    login_manager = extensions.get("login_manager")
    limiter = extensions.get("limiter")

    # If extensions did not provide a limiter (e.g. in lightweight dev setups),
    # provide a no-op fallback so decorators like @limiter.limit(...) remain safe.
    if limiter is None:
        class _NoopLimiter:
            def limit(self, _rule):
                def _decorator(func):
                    return func
                return _decorator

        limiter = _NoopLimiter()

    from pm_app.csrf import get_csrf_token, csrf_token_is_valid, CsrfToken

    @app.before_request
    def enforce_csrf_for_mutations():
        if app.testing:
            return None

        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None

        if request.endpoint and (
            request.endpoint.startswith("login")
            or request.endpoint == "static"
            or request.endpoint == "health"
            or request.endpoint == "logout"
        ):
            return None

        if csrf_token_is_valid():
            return None

        if request.path.startswith("/api/"):
            return jsonify({"error": "CSRF token missing or invalid"}), 400

        flash("Session verification failed. Please try again.", "danger")
        return redirect(url_for("login"))

    # USER HELPERS (moved to pm_app.users)
    from pm_app.users import load_user, manager_required, desk_required  # noqa: F401

    def technician_required(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not is_technician_role(current_user.role):
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped

    def developer_required(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != "developer":
                abort(403)
            return view_func(*args, **kwargs)
        return wrapped

    def allowed_file(filename, file_stream=None):
        if "." not in filename:
            return False
        ext = filename.rsplit(".", 1)[1].lower()
        if ext not in app.config["ALLOWED_EXTENSIONS"]:
            return False
        if file_stream is not None and not _check_image_magic(file_stream):
            return False
        return True

    def create_activity(activity_type, details):
        by = current_user.email if has_request_context() and current_user.is_authenticated else None
        sender_role = getattr(current_user, 'role', 'system') if has_request_context() and current_user.is_authenticated else 'system'
        activity = Activity(activity_type=activity_type, details=details, created_by=by, created_at=utcnow_naive())
        db.session.add(activity)
        db.session.commit()

        # On form submissions, notify staff inboxes with the full report (truncated)
        try:
            if activity_type in ("pm", "rca"):
                marker = f"FORM_SUBMITTED_ACTIVITY_{activity.id}"
                details_text = (details or '')
                snippet = details_text if len(details_text) <= 4000 else details_text[:4000] + "\n...[truncated]"
                body = (
                    f"{marker}\n"
                    f"New {activity.activity_type.upper()} form submitted: #{activity.id}\n"
                    f"Submitted by: {by or 'Unknown'}\n"
                    f"Created at: {activity.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "Please review and prioritize as needed."
                    f"\n\nForm details:\n{snippet}"
                )
                db.session.add(Message(
                    sender_email=by or 'system@soliton',
                    sender_role=sender_role or 'system',
                    recipient_role='staff',
                    recipient_email=None,
                    body=body,
                    created_at=utcnow_naive(),
                ))
                db.session.commit()
        except Exception:
            # Never let notification failures break form submission
            try:
                db.session.rollback()
            except Exception:
                pass

    maintenance_service = MaintenanceService(
        db=db,
        activity_model=Activity,
        message_model=Message,
        user_model=User,
        create_activity=create_activity,
        get_public_holidays=get_public_holidays,
        utcnow_naive=utcnow_naive,
        high_risk_threshold=HIGH_RISK_THRESHOLD,
        sla_scan_cooldown_seconds=app.config["INLINE_MAINTENANCE_MIN_INTERVAL_SECONDS"],
        due_soon_hours=SLA_DUE_SOON_HOURS,
        due_soon_alert_cooldown_hours=_SLA_DUE_SOON_ALERT_COOLDOWN_HOURS,
        overdue_escalation_cooldown_hours=_SLA_OVERDUE_ESCALATION_COOLDOWN_HOURS,
        auto_escalation_enabled=bool(
            app.config.get("ENABLE_INLINE_AUTOMATIONS", False) or app.config.get("SLA_ESCALATION_ENABLED", False)
        ),
    )
    app.config["MAINTENANCE_SERVICE"] = maintenance_service

    @app.cli.command("run-maintenance")
    def run_maintenance_command():
        summary = maintenance_service.run_all(respect_cooldown=False)
        click.echo(
            " ".join(f"{key}={value}" for key, value in summary.as_dict().items())
        )

    def get_user_sla_policy(user_settings: UserSettings | None):
        if not user_settings:
            return None
        preferences = user_settings.get_preferences()
        raw_policy = preferences.get("sla_policy") if isinstance(preferences, dict) else None
        if not isinstance(raw_policy, dict):
            return None
        return normalize_sla_policy_config(raw_policy)

    def get_active_sla_policy():
        settings_rows = (
            db.session.query(UserSettings, User)
            .join(User, UserSettings.user_id == User.id)
            .filter(User.role.in_(tuple(DESK_ROLES)), User.is_blocked.is_(False))
            .order_by(UserSettings.updated_at.desc())
            .all()
        )
        for user_settings, user in settings_rows:
            policy = get_user_sla_policy(user_settings)
            if not policy or not policy["policy_agreed"]:
                continue
            policy["updated_by"] = user.display_name or user.email
            policy["updated_role"] = normalize_role(user.role)
            policy["source"] = "saved"
            return policy
        return normalize_sla_policy_config(
            {
                "enabled": True,
                "standard_hours": SLA_HOURS_STANDARD,
                "critical_hours": SLA_HOURS_CRITICAL,
                "due_soon_hours": SLA_DUE_SOON_HOURS,
                "policy_agreed": True,
                "updated_by": "System Default",
                "updated_role": "system",
                "source": "default",
            }
        )

    app.config["_get_active_sla_policy"] = get_active_sla_policy
    app.config["_get_user_sla_policy"] = get_user_sla_policy

    def find_site_history(site_id, limit=5):
        if not site_id:
            return []
        return (
            Activity.query.filter(
                Activity.activity_type.in_(["pm", "rca"]),
                Activity.details.ilike(f"%Site Number: {site_id}%")
                | Activity.details.ilike(f"%Site ID: {site_id}%"),
            )
            .order_by(Activity.created_at.desc())
            .limit(limit)
            .all()
        )

    def build_form_insights(form_data, photo_lines, activity_type):
        errors = []
        anomalies = []
        recommendations = []
        critical_flags = []
        def get_value(label):
            return (form_data.get(f"field_{slugify_label(label)}") or "").strip()
        site_id = get_value("Site Number")
        site_name = get_value("Site Name")
        validation_comments = (form_data.get("validation_comments") or "").strip()
        if photo_lines and not site_id:
            errors.append("Site Number is required when photos are uploaded.")
        if not site_id or not site_name:
            errors.append("Site Number and Site Name are required.")
        snag_analysis = detect_snags_from_form(form_data)
        detected_snags = snag_analysis["snags"]
        critical_snags = snag_analysis["critical_snags"]
        outage_detected = snag_analysis["outage_detected"]
        snag_profile = summarize_snag_profile(detected_snags)
        if detected_snags:
            anomalies.append("Detected snags: " + ", ".join(detected_snags))
            recommendations.append("Resolve all detected snags and document closure evidence.")
        if outage_detected:
            critical_flags.append("Outage class snag detected")
            recommendations.append("Escalate outage-class snag to desk manager immediately.")
        if critical_snags and not photo_lines:
            errors.append("Critical snag detected. Upload evidence photos before submission.")
        if critical_snags and not validation_comments:
            errors.append("Critical snag detected. Add technician validation comments before submission.")
        risk_score = 10 if activity_type == "pm" else 20
        risk_score += snag_profile["risk_boost"]
        ats_working = get_value("Is ATS Working?").lower()
        controller_auto = get_value("Is controller in Auto mode?").lower()
        dg_battery_ok = get_value("Is Battery on DG Working?").lower()
        battery_condition = get_value("Battery Condition").lower()
        grid_faults = get_value("Any grid faults identified? Share.")
        if ats_working == "no":
            critical_flags.append("ATS is not working")
            recommendations.append("Recheck ATS wiring, contactor health, and retest ATS failover.")
            risk_score += 28
        if controller_auto == "no":
            critical_flags.append("DG controller is not in Auto mode")
            recommendations.append("Set DG controller to Auto mode and verify alarm-free state.")
            risk_score += 18
        if dg_battery_ok == "no":
            critical_flags.append("DG battery is not working")
            recommendations.append("Test starter battery voltage and replace battery if below threshold.")
            risk_score += 22
        if any(term in battery_condition for term in ["poor", "bad", "fault", "weak"]):
            critical_flags.append("Battery condition indicates fault")
            recommendations.append("Escalate battery bank health issue and schedule replacement.")
            risk_score += 18
        if grid_faults:
            recommendations.append("Validate and document grid fault root cause with NOC.")
            risk_score += 8
        if len(photo_lines) < 4:
            recommendations.append("Capture complete photo evidence before final closure.")
            risk_score += 15
        if not validation_comments:
            recommendations.append("Add technician validation comments for clearer desk review.")
            risk_score += 8
        history_records = find_site_history(site_id, limit=6)
        current_run_hours = parse_float_value(get_value("Current DG Run Hours"))
        current_grid_meter = parse_float_value(get_value("Grid Meter Reading"))
        previous_run_hours = None
        previous_grid_meter = None
        repeat_ats_faults = 0
        repeat_site_outages = 0
        repeat_site_snag_load = 0
        for record in history_records:
            if record.details and "Is ATS Working: No" in record.details:
                repeat_ats_faults += 1
            record_snags = extract_detected_snags_from_details(record.details)
            repeat_site_snag_load += len(record_snags)
            record_flags = parse_activity_kv(record.details)
            if (record_flags.get("outage detected") or "").strip().lower() == "yes":
                repeat_site_outages += 1
            if previous_run_hours is None:
                previous_run_hours = extract_metric_from_details(record.details, "Current DG Run Hours")
            if previous_grid_meter is None:
                previous_grid_meter = extract_metric_from_details(record.details, "Grid Meter Reading")
        if repeat_ats_faults >= 2:
            anomalies.append("Repeated ATS faults seen in recent submissions.")
            recommendations.append("Escalate repeated ATS faults for deeper root cause analysis.")
            risk_score += 20
        if repeat_site_outages >= 2:
            critical_flags.append("Recurring outage pattern on this site")
            anomalies.append("This site has repeated outage indicators in recent history.")
            recommendations.append("Treat this site as recurring outage pressure and prioritize permanent corrective action.")
            risk_score += 15
        if repeat_site_snag_load >= 6:
            anomalies.append("High repeat snag load detected from recent site history.")
            recommendations.append("Review recurring snags against preventive maintenance completion quality.")
            risk_score += 10
        if previous_run_hours is not None and current_run_hours is not None:
            jump = current_run_hours - previous_run_hours
            if jump < 0:
                errors.append("Current DG Run Hours cannot be less than the previous site reading.")
            elif jump > 500:
                anomalies.append(f"DG run-hour jump is unusually high ({jump:.0f} hours).")
                recommendations.append("Verify DG run-hour meter reading and investigate abnormal usage.")
                risk_score += 20
        if previous_grid_meter is not None and current_grid_meter is not None and current_grid_meter < previous_grid_meter:
            anomalies.append("Grid meter reading dropped below previous value.")
            recommendations.append("Confirm grid meter replacement/reset and record the reason.")
            risk_score += 12
        outage_context_text = " | ".join(
            value
            for value in [
                validation_comments,
                grid_faults,
                get_value("Comment"),
                get_value("Purpose of Visit"),
            ]
            if value
        )
        outage_analysis = analyze_outage_signals(outage_context_text)
        if outage_analysis["matched_signals"]:
            anomalies.append(
                "Outage indicators detected from technician narrative: "
                + ", ".join(sorted(set(outage_analysis["matched_signals"])))
                + "."
            )
            risk_score += outage_analysis["risk_boost"]
            for flag in outage_analysis["critical_flags"]:
                if flag not in critical_flags:
                    critical_flags.append(flag)
            for rec in outage_analysis["recommendations"]:
                if rec not in recommendations:
                    recommendations.append(rec)
        incident_categories = sorted(set(snag_profile["categories"] + outage_analysis.get("categories", [])))
        if outage_detected and "OUTAGE_RESPONSE" not in incident_categories:
            incident_categories.append("OUTAGE_RESPONSE")
        if not incident_categories:
            incident_categories = ["ROUTINE_PM" if activity_type == "pm" else "GENERAL_REVIEW"]
        if incident_categories[0] != "OUTAGE_RESPONSE" and "OUTAGE_RESPONSE" in incident_categories:
            incident_categories.insert(0, incident_categories.pop(incident_categories.index("OUTAGE_RESPONSE")))
        primary_category = incident_categories[0]
        issue_summary_parts = []
        if snag_profile["labels"]:
            issue_summary_parts.append(", ".join(sorted(set(snag_profile["labels"][:3]))))
        if outage_analysis["matched_signals"]:
            issue_summary_parts.append("outage signal match: " + ", ".join(sorted(set(outage_analysis["matched_signals"][:3]))))
        if repeat_site_outages >= 2:
            issue_summary_parts.append("repeat outage site pattern")
        issue_summary = "; ".join(issue_summary_parts) if issue_summary_parts else "No major snag or outage indicator detected."
        if not recommendations:
            recommendations.append("No critical issue detected. Continue routine preventive maintenance checks.")
        risk_score = max(0, min(100, int(round(risk_score))))
        risk_level = classify_risk_level(risk_score)
        is_critical = bool(critical_flags) or risk_score >= HIGH_RISK_THRESHOLD
        sla_policy = get_active_sla_policy()
        sla_deadline = build_sla_deadline_from_policy(
            activity_type=activity_type,
            is_critical=is_critical,
            now_value=utcnow_naive(),
            policy=sla_policy,
        )
        return {
            "errors": errors,
            "anomalies": anomalies,
            "recommendations": recommendations,
            "critical_flags": critical_flags,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "is_critical": is_critical,
            "sla_deadline": sla_deadline,
            "detected_snags": detected_snags,
            "outage_detected": outage_detected,
            "incident_categories": incident_categories,
            "primary_category": primary_category,
            "issue_summary": issue_summary,
        }

    def build_insight_lines(insights):
        sla_deadline_str = insights['sla_deadline'].isoformat(timespec='seconds') if insights['sla_deadline'] else "Not Set"
        lines = [
            "SMART INSIGHTS",
            f"Risk Score: {insights['risk_score']}",
            f"Risk Level: {insights['risk_level']}",
            f"Critical: {'Yes' if insights['is_critical'] else 'No'}",
            f"SLA Deadline (UTC): {sla_deadline_str}",
            f"Outage Detected: {'Yes' if insights.get('outage_detected') else 'No'}",
            f"Operational Category: {insights.get('primary_category', 'GENERAL_REVIEW')}",
            f"Incident Categories: {', '.join(insights.get('incident_categories') or []) or 'None'}",
            f"Issue Summary: {insights.get('issue_summary') or 'None'}",
            f"SLA Breach Category: {insights.get('primary_category', 'GENERAL_REVIEW')}",
            "Critical Flags:",
        ]
        if insights["critical_flags"]:
            lines.extend([f"- {item}" for item in insights["critical_flags"]])
        else:
            lines.append("- None")
        lines.append("Anomalies:")
        if insights["anomalies"]:
            lines.extend([f"- {item}" for item in insights["anomalies"]])
        else:
            lines.append("- None")
        lines.append("Recommendations:")
        lines.extend([f"- {item}" for item in insights["recommendations"]])
        lines.append("Detected Snags:")
        if insights.get("detected_snags"):
            lines.extend([f"- {item}" for item in insights["detected_snags"]])
        else:
            lines.append("- None")
        return lines

    def build_activity_review_rows(activities):
        rows = []
        now = utcnow_naive()
        active_sla_policy = get_active_sla_policy()
        due_soon_hours = active_sla_policy["due_soon_hours"]
        cache_store = app.config.setdefault("_runtime_cache", {})
        for activity in activities:
            approved_at_key = activity.approved_at.isoformat(timespec="seconds") if activity.approved_at else "none"
            review_cache_key = (
                f"activity_review:{activity.id}:{activity.risk_score}:{activity.sla_deadline}:{approved_at_key}:"
                f"{hash(activity.details or '')}:{due_soon_hours}"
            )
            # Simplified caching (original had _cache_get)
            risk_score = (activity.risk_score if activity.risk_score is not None
                          else extract_risk_score_from_details(activity.details) or 0)
            risk_level = classify_risk_level(risk_score)
            sla_deadline = activity.sla_deadline or extract_sla_deadline_from_details(activity.details)
            recommendations = extract_recommendations_from_details(activity.details)
            stage_durations = compute_activity_stage_durations(activity.details)
            values = parse_activity_kv(activity.details)
            site_number = values.get("site number") or values.get("site id") or "-"
            site_name = values.get("site name") or "-"
            issue_summary = values.get("issue summary") or values.get("issue") or values.get("validation comments (by technician)") or ""
            if activity.approved_at:
                sla_state = "Resolved"
            elif sla_deadline and now > sla_deadline:
                sla_state = "Overdue"
            elif sla_deadline and (sla_deadline - now).total_seconds() <= due_soon_hours * 3600:
                sla_state = "Due Soon"
            elif sla_deadline:
                sla_state = "On Track"
            else:
                sla_state = "Not Set"
            top_recommendation, top_recommendation_source = build_activity_suggestion_with_source(activity, recommendations, sla_state, risk_level)
            priority = build_review_priority(
                activity,
                risk_score=risk_score,
                sla_state=sla_state,
                recommendations=recommendations,
            )
            row = {
                "activity": activity,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "sla_deadline": sla_deadline,
                "sla_state": sla_state,
                "recommendations": recommendations,
                "top_recommendation": top_recommendation,
                "top_recommendation_source": top_recommendation_source,
                "stage_durations": stage_durations,
                "priority": priority,
                "site_number": site_number,
                "site_name": site_name,
                "issue_summary": issue_summary,
            }
            rows.append(row)
        rows.sort(key=lambda item: (item["priority"]["score"], item["risk_score"], item["activity"].created_at), reverse=True)
        return rows

    _TRUSTED_PROXY_COUNT = _config_int("TRUSTED_PROXY_COUNT", 0)

    def get_client_ip():
        if _TRUSTED_PROXY_COUNT > 0:
            forwarded_for = request.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                addrs = [a.strip() for a in forwarded_for.split(",")]
                idx = max(0, len(addrs) - _TRUSTED_PROXY_COUNT)
                return addrs[idx]
        return request.remote_addr or "unknown"

    def login_throttle_key(email):
        return f"{get_client_ip()}::{(email or '').strip().lower()}"

    def get_lockout_seconds(email):
        return login_throttle_store.get_lockout_seconds(login_throttle_key(email))

    def register_login_failure(email):
        login_throttle_store.register_failure(login_throttle_key(email))

    def reset_login_failures(email):
        login_throttle_store.reset(login_throttle_key(email))

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'"
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if "text/html" in (response.content_type or ""):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        started_at = getattr(g, "request_started_at", None)
        duration_ms = ((_time.perf_counter() - started_at) * 1000) if started_at is not None else 0
        slow_threshold = _config_int("SLOW_REQUEST_ALERT_MS", 5000)
        if response.status_code >= 500:
            send_alert(
                f"PM/RCA server error\nPath: {request.path}\nStatus: {response.status_code}\nRequest ID: {getattr(g, 'request_id', '-')}",
                subject="PM/RCA server error",
            )
        elif slow_threshold > 0 and duration_ms >= slow_threshold:
            send_alert(
                f"PM/RCA slow request\nPath: {request.path}\nDuration: {duration_ms:.0f}ms\nRequest ID: {getattr(g, 'request_id', '-')}",
                subject="PM/RCA slow request alert",
            )
        return response

    # =========================================================================
    # Authentication Routes
    # =========================================================================
    @app.route("/")
    def root() -> Response:
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        bs = db.session.query(BootstrapState).first()
        # Ensure we only skip the welcome page when bootstrap is complete
        # and at least one user exists. This prevents stale bootstrap
        # metadata from redirecting new deployments directly to login.
        users_exist = db.session.query(User).count() > 0
        if not bs or not bs.bootstrap_complete or not users_exist:
            return redirect(url_for("welcome_admin"))
        return redirect(url_for("login"))

    register_auth_routes(
        app,
        user_model=User,
        db=db,
        app_env=app_env,
        role_lock_enabled=_config_bool("ENABLE_ROLE_LOCKED_LOGIN", False),
        normalize_role=normalize_role,
        allowed_login_roles=allowed_login_roles,
        get_lockout_seconds=get_lockout_seconds,
        register_login_failure=register_login_failure,
        reset_login_failures=reset_login_failures,
        hash_password=hash_password,
    )

    # Register first-time admin setup routes
    register_setup_routes(app, db, User, BootstrapState)

    @app.route("/__build")
    def build_info() -> Response:
        return jsonify({"build": APP_BUILD_ID, "time": utcnow_naive().isoformat(timespec="seconds")})

    # =========================================================================
    # Authentication Routes
    # =========================================================================


    # =========================================================================
    # Dashboard (role‑based) – using the imported register_dashboard_routes
    # =========================================================================
    # Define the required helper functions that register_dashboard_routes expects
    get_live_dashboard_counts = _create_live_dashboard_counts_provider(
        app,
        db,
        Activity,
        User,
        Consumable,
        get_public_holidays,
        normalize_role,
        is_technician_role,
    )

    def get_photo_library_count():
        photo_dir = os.path.join(app.root_path, "photo")
        controls = app.config.get("PHOTO_LIBRARY_CONTROLS", normalize_photo_library_controls(None))
        if not os.path.isdir(photo_dir):
            return 0
        try:
            count = 0
            for name in os.listdir(photo_dir):
                lowered = name.lower()
                kind = "screenshot" if "screenshot" in lowered or "whatsapp" in lowered else "image"
                if kind == "screenshot" and not controls.get("include_screenshots", True):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in PHOTO_LIBRARY_IMAGE_EXTENSIONS and os.path.isfile(os.path.join(photo_dir, name)):
                    count += 1
            return count
        except OSError:
            return 0

    def calculate_notification_count():
        if not current_user.is_authenticated:
            return 0
        normalized_role = normalize_role(current_user.role)
        inbox_roles = {normalized_role, "all"}
        last_seen = None
        last_seen_raw = session.get("notifications_last_seen_at")
        if last_seen_raw:
            try:
                last_seen = datetime.fromisoformat(last_seen_raw)
            except ValueError:
                last_seen = None
        unread_message_query = Message.query.filter(
            (Message.recipient_role.in_(inbox_roles))
            | (Message.recipient_email == current_user.email)
        )
        if last_seen is not None:
            unread_message_query = unread_message_query.filter(Message.created_at > last_seen)
        return unread_message_query.count()

    @app.context_processor
    def inject_global_template_context():
        role = ""
        if current_user.is_authenticated:
            role = normalize_role(getattr(current_user, "role", "") or "")
        app_language = session.get("language", "en")
        supported_languages = app.config.get("SUPPORTED_LANGUAGES", SUPPORTED_LANGUAGES)
        if app_language not in supported_languages:
            app_language = "en"
        app_translations = app.config.get("SETTINGS_TRANSLATIONS", SETTINGS_TRANSLATIONS)
        active_translations = app_translations.get(app_language, app_translations["en"])
        def safe_url(endpoint, **kw):
            try:
                return url_for(endpoint, **kw)
            except Exception:
                return "#"

        return {
            "current_role": role,
            "app_theme": session.get("theme", "light"),
            "app_language": app_language,
            "app_language_direction": supported_languages.get(app_language, {}).get("dir", "ltr"),
            "supported_languages": supported_languages,
            "t": active_translations,
            "notification_count": calculate_notification_count(),
            "photo_library_count": get_photo_library_count(),
            "csrf_token": CsrfToken(),
            "public_holidays": get_public_holidays(),
            "dashboard_menu": get_dashboard_menu_for_role(role),
            "manager_can_approve": app.config.get("MANAGER_CAN_APPROVE", False),
            "safe_url": safe_url,
        }

    # Register small utility functions as Jinja globals so routes/templates can access them
    try:
        app.jinja_env.globals['load_site_master'] = load_site_master
        app.jinja_env.globals['slugify_label'] = slugify_label
        app.jinja_env.globals['is_yes_no_label'] = is_yes_no_label
        app.jinja_env.globals['get_public_holidays'] = get_public_holidays
        app.jinja_env.globals['normalize_role'] = normalize_role
        # Add JSON parsing filter for templates
        app.jinja_env.filters['from_json'] = lambda x: json.loads(x) if isinstance(x, str) else x
    except Exception:
        # Avoid startup failure if Jinja environment isn't ready for assignment
        pass

    # Register all dashboard routes (this will add /dashboard/, /notifications/, /settings/, etc.)
    register_dashboard_routes(
        app,
        user_model=User,
        activity_model=Activity,
        message_model=Message,
        db=db,
        normalize_role=normalize_role,
        is_technician_role=is_technician_role,
        get_live_dashboard_counts=get_live_dashboard_counts,
        calculate_notification_count=calculate_notification_count,
        create_activity=create_activity,
        get_active_sla_policy=get_active_sla_policy,
    )
    app.config["_get_live_dashboard_counts"] = get_live_dashboard_counts
    app.config["_get_active_sla_policy"] = get_active_sla_policy

    @app.route("/api/live-dashboard-counts")
    @login_required
    def api_live_dashboard_counts() -> Response:
        try:
            counts = app.config["_get_live_dashboard_counts"]() or {}
            latest_message = (
                Message.query.filter(
                    (Message.recipient_role.in_({normalize_role(current_user.role), "all"}))
                    | (Message.recipient_email == current_user.email)
                    | (Message.sender_email == current_user.email)
                )
                .order_by(Message.created_at.desc())
                .first()
            )
            notification_count = calculate_notification_count()

            return jsonify(
                {
                    "counts": counts,
                    "notification_count": notification_count,
                    "latest_message_id": latest_message.id if latest_message else None,
                    "server_time": utcnow_naive().isoformat(timespec="seconds"),
                }
            )
        except Exception as e:
            current_app.logger.exception("api_live_dashboard_counts failed: %s", e)
            # Return a safe error payload to the client; avoid exposing internals
            return jsonify({"status": "error", "code": "dashboard_counts_error", "message": "Failed to compute live dashboard counts."}), 500

    @app.route("/api/site-master")
    @login_required
    def api_site_master() -> Response:
        return jsonify({"sites": site_master_options(), "count": len(site_master_options())})

    register_api_routes(
        app,
        consumable_model=Consumable,
        activity_model=Activity,
        db=db,
        normalize_role=normalize_role,
        limiter=limiter,
    )

    register_content_routes(
        app,
        Consumable=Consumable,
        Activity=Activity,
        db=db,
        normalize_photo_library_controls=normalize_photo_library_controls,
        PHOTO_LIBRARY_IMAGE_EXTENSIONS=PHOTO_LIBRARY_IMAGE_EXTENSIONS,
        AVATAR_KEYS=AVATAR_KEYS,
        TECHNICIAN_PHOTO_FIELDS=TECHNICIAN_PHOTO_FIELDS,
        describe_monitored_image=describe_monitored_image,
        get_record_or_404=get_record_or_404,
        analyze_uploaded_photo_quality=analyze_uploaded_photo_quality,
        describe_uploaded_photo=describe_uploaded_photo,
    )

    register_admin_routes(
        app,
        User=User,
        UserSettings=UserSettings,
        Activity=Activity,
        PasswordResetToken=PasswordResetToken,
        db=db,
        create_activity=create_activity,
        normalize_photo_library_controls=normalize_photo_library_controls,
        LOGIN_MATRIX_KEYS=LOGIN_MATRIX_KEYS,
        normalize_role=normalize_role,
        VALID_ACCOUNT_ROLES=VALID_ACCOUNT_ROLES,
        AVATAR_KEYS=AVATAR_KEYS,
        get_record_or_404=get_record_or_404,
        send_password_reset_email=send_password_reset_email,
        generate_password_hash=generate_password_hash,
        secrets=secrets,
        utcnow_naive=utcnow_naive,
        AuditLog=AuditLog,
    )

    @app.route("/field/site-form/")
    @login_required
    def field_site_form():
        return redirect(url_for("dashboard"))

    # =========================================================================
    # Technician Routes (extracted)
    # =========================================================================
    from pm_app.technician.routes import register_technician_routes
    register_technician_routes(
        app,
        Activity=Activity,
        Message=Message,
        FormAssignment=FormAssignment,
        User=User,
        db=db,
        TECHNICIAN_PM_SECTIONS=TECHNICIAN_PM_SECTIONS,
        TECHNICIAN_PHOTO_FIELDS=TECHNICIAN_PHOTO_FIELDS,
        allowed_file=allowed_file,
        _check_image_magic=_check_image_magic,
        analyze_uploaded_photo_quality=analyze_uploaded_photo_quality,
        describe_uploaded_photo=describe_uploaded_photo,
        save_signature_image=save_signature_image,
        collect_technician_form_details=collect_technician_form_details,
        build_form_insights=build_form_insights,
        parse_activity_details_structured=parse_activity_details_structured,
        parse_activity_kv=parse_activity_kv,
        get_record_or_404=get_record_or_404,
        utcnow_naive=utcnow_naive,
        secure_filename=secure_filename,
        AuditLog=AuditLog,
    )

    # =========================================================================
    # Desk Routes (full original)
    # =========================================================================
    @app.route("/desk/activities/")
    @login_required
    @desk_required
    def desk_activities() -> str:
        view_mode = (request.args.get("mode") or "rcas").strip().lower()
        if view_mode not in {"rcas", "forms", "rejected"}:
            view_mode = "rcas"
        type_filter = (request.args.get("type") or "").strip().lower()
        review_filter = (request.args.get("review") or "").strip().lower()
        search_query = (request.args.get("q") or "").strip()[:100]
        created_on = (request.args.get("date") or "").strip()
        month_filter = (request.args.get("month") or "").strip()
        risk_filter = (request.args.get("risk") or "").strip().lower()
        sla_filter = (request.args.get("sla") or "").strip().lower()

        query = Activity.query.filter(Activity.activity_type.in_(["pm", "rca"]))
        if type_filter in {"pm", "rca"}:
            query = query.filter(Activity.activity_type == type_filter)
        if view_mode == "rcas":
            query = query.filter(Activity.approved_at.is_(None))
        elif view_mode == "rejected":
            query = query.filter(Activity.is_approved.is_(False), Activity.approved_at.is_not(None))
        elif view_mode == "forms":
            if review_filter == "reviewed":
                query = query.filter(Activity.approved_at.is_not(None))
            elif review_filter == "approved":
                query = query.filter(Activity.is_approved.is_(True), Activity.approved_at.is_not(None))
            elif review_filter == "pending":
                query = query.filter(Activity.approved_at.is_(None))

        if search_query:
            like = f"%{search_query}%"
            filters = [
                Activity.details.ilike(like),
                Activity.created_by.ilike(like),
                Activity.activity_type.ilike(like),
            ]
            if search_query.isdigit():
                filters.append(Activity.id == int(search_query))
            query = query.filter(or_(*filters))
        if created_on:
            try:
                day_start = datetime.fromisoformat(created_on)
                day_end = day_start + timedelta(days=1)
                query = query.filter(Activity.created_at >= day_start, Activity.created_at < day_end)
            except ValueError:
                created_on = ""
        if month_filter:
            try:
                month_start = datetime.strptime(month_filter, "%Y-%m")
                next_month = month_start.replace(day=28) + timedelta(days=4)
                month_end = next_month.replace(day=1)
                query = query.filter(Activity.created_at >= month_start, Activity.created_at < month_end)
            except Exception:
                month_filter = ""
        if risk_filter == "high":
            query = query.filter(Activity.risk_score >= HIGH_RISK_THRESHOLD)
        elif risk_filter == "medium":
            query = query.filter(Activity.risk_score >= MEDIUM_RISK_THRESHOLD, Activity.risk_score < HIGH_RISK_THRESHOLD)
        elif risk_filter == "low":
            query = query.filter(or_(Activity.risk_score < MEDIUM_RISK_THRESHOLD, Activity.risk_score.is_(None)))
        if sla_filter == "overdue":
            query = query.filter(Activity.sla_deadline.is_not(None), Activity.sla_deadline < utcnow_naive())
        elif sla_filter == "due_soon":
            cutoff = utcnow_naive() + timedelta(hours=get_active_sla_policy()["due_soon_hours"])
            query = query.filter(Activity.sla_deadline.is_not(None), Activity.sla_deadline >= utcnow_naive(), Activity.sla_deadline <= cutoff)
        elif sla_filter == "on_track":
            cutoff = utcnow_naive() + timedelta(hours=get_active_sla_policy()["due_soon_hours"])
            query = query.filter(Activity.sla_deadline.is_not(None), Activity.sla_deadline > cutoff)

        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(max(10, request.args.get("per_page", 20, type=int)), 100)
        pagination = query.order_by(Activity.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return render_template(
            "desk_activities.html",
            view_mode=view_mode,
            type_filter=type_filter,
            review_filter=review_filter,
            search_query=search_query,
            created_on=created_on,
            month_filter=month_filter,
            risk_filter=risk_filter,
            sla_filter=sla_filter,
            review_rows=build_activity_review_rows(pagination.items),
            pagination=pagination,
            active_sla_policy=get_active_sla_policy(),
        )

    register_desk_routes(
        app,
        Activity=Activity,
        FormAssignment=FormAssignment,
        Message=Message,
        User=User,
        db=db,
        get_active_sla_policy=get_active_sla_policy,
        build_activity_review_rows=build_activity_review_rows,
        get_record_or_404=get_record_or_404,
        build_activity_pdf_buffer=build_activity_pdf_buffer,
        parse_activity_kv=parse_activity_kv,
        parse_activity_details_structured=parse_activity_details_structured,
        utcnow_naive=utcnow_naive,
        classify_risk_level=classify_risk_level,
        extract_recommendations_from_details=extract_recommendations_from_details,
    )

    from pm_app.activities.routes import bp as activities_bp, register_activity_routes, register_activity_app_handlers
    
    app.register_blueprint(activities_bp)
    register_activity_routes(app, create_activity=create_activity)
    register_activity_app_handlers(app)

    # Legacy admin and content routes are now registered inside pm_app.activities.routes
    # route moved to pm_app.content.routes
    @login_required
    def consumables():
            if request.method == "POST":
                site_id = (request.form.get("site_id") or "").strip()[:20]
                site_name = (request.form.get("site_name") or "").strip()[:120]
                description = (request.form.get("description") or "").strip()
                if not site_id or not site_name or not description:
                    flash("Site ID, site name, and description are required.", "warning")
                    return redirect(url_for("consumables"))
                item = Consumable(
                    site_id=site_id,
                    site_name=site_name,
                    description=description,
                    created_by=current_user.email,
                    location=(request.form.get("location") or "").strip() or None,
                    signage_image_url=(request.form.get("signage_image_url") or "").strip() or None,
                    screenshot_url=(request.form.get("screenshot_url") or "").strip() or None,
                    before_usage_image_url=(request.form.get("before_usage_image_url") or "").strip() or None,
                )
                db.session.add(item)
                db.session.commit()
                flash("Consumable saved.", "success")
                return redirect(url_for("consumables"))
    
            search_query = (request.args.get("q") or "").strip()[:100]
            query = Consumable.query
            if search_query:
                like = f"%{search_query}%"
                query = query.filter(or_(
                    Consumable.site_id.ilike(like),
                    Consumable.site_name.ilike(like),
                    Consumable.description.ilike(like),
                    Consumable.created_by.ilike(like),
                ))
            page = max(1, request.args.get("page", 1, type=int))
            per_page = min(max(10, request.args.get("per_page", 25, type=int)), 100)
            pagination = query.order_by(Consumable.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
            return render_template("consumables.html", consumables=pagination.items, pagination=pagination, search_query=search_query)
    
        # route moved to pm_app.content.routes
    @login_required
    def consumable_detail(item_id):
            item = get_record_or_404(Consumable, item_id)
            return render_template("consumable_detail.html", item=item)
    
        # route moved to pm_app.content.routes
    @login_required
    @developer_required
    def developer_photo_library():
            controls = app.config.get("PHOTO_LIBRARY_CONTROLS", normalize_photo_library_controls(None))
            photo_query = (request.args.get("q") or "").strip().lower()
            requested_limit = request.args.get("limit", controls["max_scan_limit"], type=int)
            photo_limit = min(max(requested_limit or 12, 12), controls["max_scan_limit"])
            photo_dir = os.path.join(app.root_path, "photo")
            candidates = []
            if os.path.isdir(photo_dir):
                for name in os.listdir(photo_dir):
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in PHOTO_LIBRARY_IMAGE_EXTENSIONS:
                        continue
                    lowered = name.lower()
                    kind = "screenshot" if "screenshot" in lowered or "whatsapp" in lowered else "image"
                    if kind == "screenshot" and not controls["include_screenshots"]:
                        continue
                    path = os.path.join(photo_dir, name)
                    if photo_query and photo_query not in lowered:
                        continue
                    stat = os.stat(path)
                    candidates.append({
                        "name": name,
                        "path": path,
                        "extension": ext.lstrip("."),
                        "kind": kind,
                        "size_kb": max(1, round(stat.st_size / 1024)),
                        "modified_at": datetime.fromtimestamp(stat.st_mtime),
                        "preview_url": url_for("photo_library_file", filename=name),
                    })
            candidates.sort(key=lambda item: item["modified_at"], reverse=True)
            entries = candidates[:photo_limit]
            for entry in entries:
                entry["description"] = describe_monitored_image(entry["path"], entry["name"])
                entry.pop("path", None)
            return render_template(
                "developer_photo_library.html",
                photo_entries=entries,
                photo_library_total=len(entries),
                screenshot_count=sum(1 for item in entries if item["kind"] == "screenshot"),
                photo_library_path=photo_dir,
                monitored_sources=[photo_dir],
                photo_query=request.args.get("q", ""),
                photo_limit=photo_limit,
                photo_library_controls=controls,
            )
    
        # route moved to pm_app.content.routes
    @login_required
    @developer_required
    def photo_library_file(filename):
            return send_from_directory(os.path.join(app.root_path, "photo"), filename)
    
        # route moved to pm_app.content.routes
    @login_required
    @developer_required
    def import_photo_library_file():
            controls = app.config.get("PHOTO_LIBRARY_CONTROLS", normalize_photo_library_controls(None))
            if not controls.get("allow_import"):
                flash("Photo import is disabled by developer policy.", "warning")
                return redirect(url_for("developer_photo_library"))
            filename = secure_filename(request.form.get("filename") or "")
            source = os.path.join(app.root_path, "photo", filename)
            if not filename or not os.path.isfile(source) or not _is_valid_image_file_path(source):
                flash("Selected photo could not be imported.", "danger")
                return redirect(url_for("developer_photo_library"))
            dest_name = f"photo_library_{uuid.uuid4().hex}_{filename}"
            shutil.copy2(source, os.path.join(app.config["UPLOAD_FOLDER"], dest_name))
            flash("Photo imported into uploads.", "success")
            return redirect(url_for("developer_photo_library"))
    
        # route moved to pm_app.content.routes
    @login_required
    @developer_required
    def developer_share_qr():
            requested_url = request.args.get("url") or resolve_share_context()["login_url"]
            image_format = (request.args.get("format") or "png").lower()
            drawing = Drawing(220, 220)
            qr_code = reportlab_qr.QrCodeWidget(requested_url)
            bounds = qr_code.getBounds()
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            qr_code.barWidth = 190 / width
            qr_code.barHeight = 190 / height
            qr_code.x = 15
            qr_code.y = 15
            drawing.add(qr_code)
            if image_format == "svg":
                data = renderSVG.drawToString(drawing)
                return app.response_class(data, mimetype="image/svg+xml")
            buffer = io.BytesIO()
            renderPM.drawToFile(drawing, buffer, fmt="PNG")
            buffer.seek(0)
            return send_file(buffer, mimetype="image/png")
    
        # route moved to pm_app.content.routes
    @login_required
    @developer_required
    def system_share_url():
            share_context = resolve_share_context()
            lan_ip = "192.168.1.83"
            try:
                import socket
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                probe.connect(("8.8.8.8", 80))
                lan_ip = probe.getsockname()[0]
                probe.close()
            except Exception:
                pass
            request_base = urlparse(request.host_url.rstrip("/"))
            request_scheme = request_base.scheme or "http"
            request_port = request_base.port
            port_suffix = f":{request_port}" if request_port and request_port not in {80, 443} else ""
            lan_url = f"{request_scheme}://{lan_ip}{port_suffix}/login/"
            return render_template("system_share_url.html", public_login_url=share_context["login_url"], public_url_source=share_context["source"], lan_url=lan_url)
    
        # route moved to pm_app.content.routes
    @login_required
    @developer_required
    def api_live_share_url():
            share_context = resolve_share_context()
            return jsonify(share_context)
    
    def _tracker_rows():
            activities = Activity.query.filter(Activity.activity_type.in_(["pm", "rca"])).order_by(Activity.created_at.desc()).all()
            labels = ["Site Number", "Site Name", "Issue Summary", "Risk Score", "Risk Level"]
            rows = []
            for activity in activities:
                values = parse_activity_kv(activity.details)
                rows.append({
                    "form_id": activity.id,
                    "activity_type": activity.activity_type.upper(),
                    "site_number": values.get("site number") or values.get("site id") or "-",
                    "site_name": values.get("site name") or "-",
                    "technician": activity.created_by or "-",
                    "created_at": activity.created_at.strftime("%Y-%m-%d %H:%M") if activity.created_at else "-",
                    "status": "Approved" if activity.is_approved else ("Rejected" if activity.approved_at else "Pending"),
                    "approved_by": activity.approved_by,
                    "approved_at": activity.approved_at.strftime("%Y-%m-%d %H:%M") if activity.approved_at else "",
                    "field_values": {
                        "Site Number": values.get("site number") or values.get("site id") or "-",
                        "Site Name": values.get("site name") or "-",
                        "Issue Summary": values.get("issue summary") or values.get("issue") or "-",
                        "Risk Score": values.get("risk score") or str(activity.risk_score or 0),
                        "Risk Level": values.get("risk level") or classify_risk_level(activity.risk_score or 0),
                    },
                })
            return labels, rows
    
        # route moved to pm_app.content.routes
    @login_required
    @desk_required
    def desk_rca_tracker():
            labels, rows = _tracker_rows()
            return render_template("desk_rca_tracker.html", labels=labels, rows=rows)
    
        # route moved to pm_app.content.routes
    @login_required
    @desk_required
    def staff_rca_tracker():
            return redirect(url_for("desk_rca_tracker"))
    
        # route moved to pm_app.content.routes
    @login_required
    @desk_required
    def export_rca_tracker_excel():
            labels, rows = _tracker_rows()
            wb = Workbook()
            ws = wb.active
            assert ws is not None
            ws.title = "PM RCA Tracker"
            header = ["Form ID", "Type", "Site Number", "Site Name", "Technician", "Created At", "Status", "Approved By", "Approved At"] + labels
            ws.append(header)
            for row in rows:
                ws.append([
                    row["form_id"], row["activity_type"], row["site_number"], row["site_name"], row["technician"],
                    row["created_at"], row["status"], row["approved_by"] or "", row["approved_at"] or "",
                    *[row["field_values"].get(label, "") for label in labels],
                ])
            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            as_attachment = request.args.get("mode") != "open"
            return send_file(buffer, as_attachment=as_attachment, download_name="pm_rca_tracker.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
        # route moved to pm_app.content.routes
    @login_required
    @desk_required
    def export_staff_rca_tracker_excel():
            return export_rca_tracker_excel()
    
        # route moved to pm_app.content.routes
    @login_required
    @desk_required
    def export_approved_forms_excel():
            return export_rca_tracker_excel()
    
    @app.route("/desk/sla-system/")
    @login_required
    @desk_required
    def desk_sla_system():
            activities = Activity.query.filter(Activity.activity_type.in_(["pm", "rca"])).order_by(Activity.created_at.desc()).limit(50).all()
            rows = build_activity_review_rows(activities)
            total = len(rows)
            overdue = sum(1 for row in rows if row["sla_state"] == "Overdue")
            due_soon = sum(1 for row in rows if row["sla_state"] == "Due Soon")
            on_track = sum(1 for row in rows if row["sla_state"] == "On Track")
            return render_template(
                "desk_sla_system.html",
                desk_role=normalize_role(current_user.role),
                total_items=total,
                overdue_count=overdue,
                due_soon_count=due_soon,
                on_track_count=on_track,
                no_deadline_count=sum(1 for row in rows if row["sla_state"] == "Not Set"),
                sla_recovery_rate=0,
                recovered_within_24h=0,
                overdue_resolved_total=0,
                repeat_offender_index=0,
                top_pressure_sites=[],
                top_breach_categories=[],
                top_snag_sites=[],
                top_snag_technicians=[],
                active_sla_policy=get_active_sla_policy(),
                now_value=utcnow_naive(),
                review_rows=rows[:12],
                format_duration_seconds=format_duration_seconds,
            )
    
    @app.route("/emergency/")
    @login_required
    def emergency():
            return render_template("emergency.html")
    
    @app.route("/uploads/<filename>")
    @login_required
    def uploaded_file(filename):
            return send_from_directory(app.config["UPLOAD_FOLDER"], filename)
    
    @app.route("/health")
    def health():
            """Comprehensive health check endpoint."""
            checks = {
                'database': {'status': 'unknown', 'message': ''},
                'redis': {'status': 'unknown', 'message': ''},
                'disk_space': {'status': 'unknown', 'message': ''},
                'memory': {'status': 'unknown', 'message': ''},
                'cpu': {'status': 'unknown', 'message': ''},
            }
            overall_status = "healthy"

            # Database check
            try:
                result = db.session.execute(text("SELECT 1")).scalar()
                if result == 1:
                    checks['database'] = {'status': 'healthy', 'message': 'Database connection OK'}
                else:
                    checks['database'] = {'status': 'unhealthy', 'message': 'Database query failed'}
                    overall_status = "unhealthy"
            except Exception as e:
                checks['database'] = {'status': 'unhealthy', 'message': f'Database error: {str(e)}'}
                overall_status = "unhealthy"

            # Redis check
            redis_client = app.config.get('REDIS_CLIENT')
            if redis_client:
                try:
                    if redis_client.ping():
                        checks['redis'] = {'status': 'healthy', 'message': 'Redis connection OK'}
                    else:
                        checks['redis'] = {'status': 'unhealthy', 'message': 'Redis ping failed'}
                        overall_status = "degraded"
                except Exception as e:
                    checks['redis'] = {'status': 'unavailable', 'message': f'Redis error: {str(e)}'}
                    overall_status = "degraded"
            else:
                checks['redis'] = {'status': 'unavailable', 'message': 'Redis client not initialized'}
                overall_status = "degraded"

            # Disk space check
            try:
                usage = psutil.disk_usage('/')
                percent = usage.percent
                if percent > 95:
                    checks['disk_space'] = {'status': 'critical', 'message': f'Disk {percent:.1f}% full'}
                    overall_status = "critical"
                elif percent > 85:
                    checks['disk_space'] = {'status': 'warning', 'message': f'Disk {percent:.1f}% full'}
                    if overall_status == "healthy":
                        overall_status = "degraded"
                else:
                    checks['disk_space'] = {'status': 'healthy', 'message': f'Disk {percent:.1f}% used'}
            except Exception as e:
                checks['disk_space'] = {'status': 'error', 'message': f'Disk check failed: {str(e)}'}

            # Memory check
            try:
                memory = psutil.virtual_memory()
                percent = memory.percent
                if percent > 95:
                    checks['memory'] = {'status': 'critical', 'message': f'Memory {percent:.1f}% used'}
                    overall_status = "critical"
                elif percent > 85:
                    checks['memory'] = {'status': 'warning', 'message': f'Memory {percent:.1f}% used'}
                    if overall_status == "healthy":
                        overall_status = "degraded"
                else:
                    checks['memory'] = {'status': 'healthy', 'message': f'Memory {percent:.1f}% used'}
            except Exception as e:
                checks['memory'] = {'status': 'error', 'message': f'Memory check failed: {str(e)}'}

            # CPU check
            try:
                cpu_percent = psutil.cpu_percent(interval=0.5)
                if cpu_percent > 95:
                    checks['cpu'] = {'status': 'critical', 'message': f'CPU {cpu_percent:.1f}%'}
                    overall_status = "critical"
                elif cpu_percent > 85:
                    checks['cpu'] = {'status': 'warning', 'message': f'CPU {cpu_percent:.1f}%'}
                    if overall_status == "healthy":
                        overall_status = "degraded"
                else:
                    checks['cpu'] = {'status': 'healthy', 'message': f'CPU {cpu_percent:.1f}%'}
            except Exception as e:
                checks['cpu'] = {'status': 'error', 'message': f'CPU check failed: {str(e)}'}

            # Build response
            response = {
                'status': overall_status,
                'timestamp': utcnow_naive().isoformat(),
                'checks': checks,
                'uptime': psutil.boot_time(),
            }

            # Log issues
            for component, check in checks.items():
                if check['status'] in ['critical', 'unhealthy']:
                    logger = logging.getLogger(__name__)
                    logger.error(f"Health check {component}: {check['message']}")

            status_code = 200 if overall_status in ['healthy', 'degraded'] else 503
            return jsonify(response), status_code

    @app.route("/system-status")
    @login_required
    @developer_required
    def system_status():
            integrity = _collect_startup_integrity(app)
            status = "PASS" if not integrity["blocking_failures"] else "FAIL"
            audit_history = _collect_audit_history(app)
            return jsonify(
                {
                    "status": status,
                    "environment": app.config.get("APP_ENV"),
                    "bootstrap": {
                        "complete": integrity["bootstrap_complete"],
                        "admin_exists": integrity["admin_exists"],
                        "user_count": integrity["user_count"],
                    },
                    "migrations": {
                        "current_revision": integrity["current_revision"],
                        "latest_revision": integrity["latest_revision"],
                        "out_of_date": integrity["migration_out_of_date"],
                    },
                    "services": {
                        "redis_available": integrity["redis_available"],
                        "smtp_configured": bool(os.getenv("ALERT_SMTP_HOST")),
                    },
                    "filesystem": {
                        "uploads_writable": integrity["uploads_writable"],
                        "logs_writable": integrity["logs_writable"],
                    },
                    "audit_history": audit_history,
                    "warnings": integrity["warnings"],
                    "blocking_failures": integrity["blocking_failures"],
                }
            ), 200 if status == "PASS" else 503

    @app.route("/metrics")
    def prometheus_metrics() -> Response:
            """Prometheus metrics endpoint for monitoring."""
            try:
                from prometheus_client import generate_latest, REGISTRY, Counter, Gauge, Histogram, Info
    
                # Define metrics only once
                if not getattr(app, '_prometheus_metrics_defined', False):
                    # Counters
                    Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
                    Histogram('http_request_duration_seconds', 'HTTP request duration', ['endpoint'])
    
                    # Gauges
                    Gauge('active_users_total', 'Currently active user count')
                    Gauge('total_users_total', 'Total registered users')
                    Gauge('db_pool_connections', 'Database connection pool usage')
                    Gauge('db_pool_overflow', 'Database connection pool overflow')
                    Gauge('redis_connections', 'Redis client connections')
                    Gauge('memory_usage_percent', 'System memory usage percentage')
                    Gauge('cpu_usage_percent', 'System CPU usage percentage')
                    Gauge('disk_usage_percent', 'System disk usage percentage')
    
                    # Info
                    Info('pm_system_info', 'PM System Information').info({
                        'version': os.getenv('APP_VERSION', '1.0.0'),
                        'environment': app.config.get('APP_ENV', 'unknown'),
                        'framework': 'Flask',
                    })
    
                    object.__setattr__(app, '_prometheus_metrics_defined', True)
    
                return Response(
                    generate_latest(REGISTRY),
                    status=200,
                    mimetype='text/plain; version=0.0.4; charset=utf-8'
                )
    
            except ImportError:
                return Response("Prometheus client not installed", status=503)
    
    @app.route("/admin/self-service/create-developer", methods=["GET", "POST"])
    @limiter.limit("10 per hour")  # Strict rate limiting for self-service
    def self_service_create_developer():  # type: ignore
            """
            Self-service portal for customers who purchased the system.
            Allows creation of exactly ONE developer account.
            This endpoint is hidden by default in production. Enable via SELF_SERVICE_ENABLED=true.
            """
            # Security: Check if self-service is enabled
            if not current_app.config.get("SELF_SERVICE_ENABLED", False):
                # Return 404 to hide endpoint existence completely
                abort(404)
    
            # Security: IP whitelist check (if configured)
            allowed_ips = current_app.config.get("SELF_SERVICE_ALLOWED_IPS", [])
            if allowed_ips:
                try:
                    client_ip = request.remote_addr or ""
                    client_ip_obj = ipaddress.ip_address(client_ip)
                    if not any(client_ip_obj in net for net in allowed_ips):
                        AuditLog.log(
                            action="self_service_blocked",
                            category="authentication",
                            ip_address=client_ip,
                            user_agent=request.user_agent.string[:255] if request.user_agent else None,
                            details={"reason": "IP not in whitelist"}
                        )
                        abort(403)
                except ValueError:
                    abort(403)
    
            # If any user already exists, hide this endpoint (404)
            existing_user = User.query.first()
            if existing_user:
                AuditLog.log(
                    action="self_service_blocked",
                    category="authentication",
                    ip_address=request.remote_addr,
                    user_agent=request.user_agent.string[:255] if request.user_agent else None,
                    details={"attempted_email": request.form.get('email', '') if request.method == 'POST' else 'page_view'}
                )
                abort(404)
    
            # No developer exists yet - allow registration
            if request.method == "POST":
                email = (request.form.get("email") or "").strip().lower()
                full_name = (request.form.get("full_name") or "").strip()
                first_name = (request.form.get("first_name") or "").strip()
                last_name = (request.form.get("last_name") or "").strip()
                password = request.form.get("password") or ""
                confirm_password = request.form.get("confirm_password") or ""
    
                # CSRF validation
                if not csrf_token_is_valid():
                    flash("CSRF token invalid. Please try again.", "danger")
                    return render_template("self_service_register.html")
    
                # Validation
                errors = []
                if not email:
                    errors.append("Email is required")
                elif User.query.filter(func.lower(User.email) == email).first():
                    errors.append("Email already registered")
    
                if not full_name:
                    if first_name or last_name:
                        full_name = f"{first_name} {last_name}".strip()
                    else:
                        errors.append("Full name is required")
    
                if not password:
                    errors.append("Password is required")
                elif len(password) < 8:
                    errors.append("Password must be at least 8 characters")
                elif password != confirm_password:
                    errors.append("Passwords do not match")
    
                if errors:
                    for error in errors:
                        flash(error, "danger")
                    return render_template("self_service_register.html")
    
                # Create developer user
                try:
                    user = User(
                        uid=generate_uid("developer"),
                        email=email,
                        full_name=full_name,
                        first_name=first_name or None,
                        last_name=last_name or None,
                        role="developer",
                        password_hash=hash_password(password),
                        created_at=utcnow_naive(),
                    )
                    db.session.add(user)
                    db.session.commit()

                    # Audit log
                    AuditLog.log(
                        action="developer_created_self_service",
                        category="authentication",
                        user=user.id,
                        ip_address=request.remote_addr,
                        user_agent=request.user_agent.string[:255] if request.user_agent else None,
                        details={"email": email, "full_name": full_name, "method": "self_service"}
                    )

                    # Log this special event
                    app.logger.info(f"Self-service developer account created: {email}")

                    # Send confirmation email
                    _send_welcome_email(email, full_name)  # type: ignore

                    flash("Admin account created successfully! You can now log in.", "success")
                    return redirect(url_for("login"))
                except Exception as e:
                    db.session.rollback()
                    app.logger.error(f"Failed to create developer account: {e}")
                    flash(f"An error occurred: {str(e)}", "danger")
                    return render_template("self_service_register.html")

            # GET request: show form
            return render_template("self_service_register.html")
# Send welcome email to new developer.
            report_email = os.getenv('REPORT_EMAIL') or os.getenv('ALERT_EMAIL_ADDRESS', '')
            alert_password = os.getenv('ALERT_EMAIL_PASSWORD', '')

            if not report_email or not alert_password:
                return

            try:
                base_url = get_public_base_url() or request.host_url.rstrip('/')
                body = f"""
    Hello {full_name},
    
    Your admin account has been created on the PM/RCA System.
    
    You can now log in at: {base_url}/developer/login
    
    Important:
    - Keep your credentials secure
    - You are the primary administrator for this system
    - Contact support if you need assistance
    
    Best regards,
    PM System Administrator
                """
                msg = MIMEMultipart()
                msg['From'] = report_email
                msg['To'] = email
                msg['Subject'] = "Welcome to PM/RCA System - Admin Account Created"
                msg.attach(MIMEText(body.strip(), 'plain'))

                with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                    server.login(report_email, alert_password)
                    server.send_message(msg)
            except Exception as e:
                app.logger.error(f"Failed to send welcome email: {e}")
                raise
    
    @app.errorhandler(404)
    def not_found(error):
            return render_template("not_found.html"), 404
    
    @app.errorhandler(500)
    def internal_error(error):
            db.session.rollback()
            return render_template("500.html"), 500
    
    @app.errorhandler(RequestEntityTooLarge)
    def request_entity_too_large(error):
            max_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
            flash(f"Upload failed: file exceeds {max_mb}MB limit.", "danger")
            return redirect(request.referrer or url_for("field_rca"))
    
    # Register compatibility helpers for route modules that resolve helpers via app.view_functions
    # These are handled by pm_app.activities.routes.register_activity_app_handlers

    # ==========================================
    # Initialize Celery
    # ==========================================
    try:
        from pm_app.celery import init_celery
        init_celery(app)
        app.logger.info("Celery initialized successfully")
    except Exception as e:
        app.logger.error(f"Failed to initialize Celery: {e}")
    
    @app.route("/staff/calendar/")
    @login_required
    def staff_calendar():
        import calendar
        from datetime import date
        if not current_user.is_authenticated or current_user.role not in ("staff", "manager", "general_manager"):
            abort(403)
        holidays = get_public_holidays()
        today = utcnow_naive().date()
        selected_year = request.args.get("year", type=int) or today.year
        selected_month = request.args.get("month", type=int) or today.month
        if selected_month < 1 or selected_month > 12:
            selected_month = today.month
        try:
            view_date = date(selected_year, selected_month, 1)
        except ValueError:
            view_date = today.replace(day=1)
        month_matrix = calendar.monthcalendar(view_date.year, view_date.month)
        return render_template("technician_calendar.html", holidays=holidays, month_matrix=month_matrix, today=today, view_date=view_date)

    return app
    
if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", "5001"))
    app.logger.info(f"Starting Flask app on http://0.0.0.0:{port}")
    logout_routes = [rule for rule in app.url_map.iter_rules() if rule.rule in {"/logout", "/logout/"}]
    for rule in logout_routes:
        app.logger.info(f"Logout route registered: {rule.rule} methods={sorted(rule.methods or [])}")
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", host="0.0.0.0", port=port)

