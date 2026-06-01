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
from sqlalchemy import func, or_, inspect, text
from sqlalchemy.pool import QueuePool
from alert_system import send_alert

# Local modules
from model import db, Consumable, Activity, User, Message, UserSettings, FormAssignment, AuditLog, AccountActivationToken, PasswordResetToken
from services.login_throttle import LoginThrottleStore
from pm_app.dashboards.routes import register_dashboard_routes
from pm_app.auth.routes import register_auth_routes
from pm_app.services.observability import configure_request_observability
from pm_app.api.routes import register_api_routes
from pm_app.services.maintenance import MaintenanceService
from pm_app.services.email import send_activation_email, send_password_reset_email
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

# ============================
# CONFIGURATION
# ============================
APP_BUILD_ID = os.environ.get("APP_BUILD_ID", "unknown")

# ============================
# LOGGING SETUP (PUT HERE)
# ============================


def setup_logging(app):
    for handler in list(app.logger.handlers):
        app.logger.removeHandler(handler)
        handler.close()

    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pm_app", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, "app.log")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s | %(message)s'
    )

    file_handler.setFormatter(formatter)

    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False

    app.logger.info("Logging is configured. Logs will be written to %s", log_path)
# ============================================================================
# Constants (full lists – keep exactly as in original)
# ============================================================================

_ALERT_COOLDOWN = 1800
_SLA_SCAN_COOLDOWN = 300
_SLA_DUE_SOON_ALERT_COOLDOWN_HOURS = 6
_SLA_OVERDUE_ESCALATION_COOLDOWN_HOURS = 3
HIGH_RISK_THRESHOLD = 70
MEDIUM_RISK_THRESHOLD = 40
SLA_DUE_SOON_HOURS = 6
SLA_HOURS_CRITICAL = 24
SLA_HOURS_STANDARD = 48

_INLINE_MAINTENANCE_MIN_INTERVAL_SECONDS = 120
_DASHBOARD_COUNT_CACHE_TTL_SECONDS = 20
_NOTIFICATION_BADGE_CACHE_SECONDS = 8
_PHOTO_LIBRARY_COUNT_CACHE_SECONDS = 30
_ACTIVITY_REVIEW_ROW_CACHE_SECONDS = 45

# Image magic bytes
_IMAGE_MAGIC = (
    (b'\x89PNG\r\n\x1a\n', 'png'),
    (b'\xff\xd8\xff',       'jpeg'),
    (b'GIF87a',             'gif'),
    (b'GIF89a',             'gif'),
)

ADMIN_ROLES = {"manager", "general_manager", "developer", "admin"}
DESK_ROLES = {"staff", "manager", "general_manager", "developer", "admin"}
TECHNICIAN_ROLES = {"technician"}
VALID_ACCOUNT_ROLES = ("developer", "general_manager", "manager", "admin", "staff", "technician")
LOGIN_MATRIX_KEYS = ("developer", "staff", "technician", "admin")
DEFAULT_ROLE_ACCESS_MATRIX = {
    "developer": ["developer"],
    "admin": ["admin"],
    "staff": ["staff", "manager", "general_manager"],
    "technician": ["technician"],
}

ROLE_DASHBOARD_MENU = {
    "developer":[
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "User Management", "endpoint": "admin_user_control"},
        {"label": "Security Posture", "endpoint": "admin_security_posture"},
        {"label": "Photo Library", "endpoint": "admin_photo_library"},
        {"label": "Share Login URL", "endpoint": "system_share_url"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "staff": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Desk Activities", "endpoint": "desk_activities"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "manager": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Desk Activities", "endpoint": "desk_activities"},
        {"label": "Approvals", "endpoint": "desk_activities"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "general_manager": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Desk Activities", "endpoint": "desk_activities"},
        {"label": "Approvals", "endpoint": "desk_activities"},
        {"label": "User Overview", "endpoint": "admin_staff"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
    "technician": [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Field RCA", "endpoint": "field_rca"},
        {"label": "My Submissions", "endpoint": "technician_submissions"},
        {"label": "Rejected Reports", "endpoint": "technician_rejected_reports"},
        {"label": "Calendar", "endpoint": "technician_calendar"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ],
}

AVATAR_OPTIONS = (
    {"key": "technician",  "label": "Technician",           "icon": "person-fill-gear",      "gender": "male"},
    {"key": "male_exec",   "label": "Male Office",   "icon": "person-badge-fill",     "gender": "male"},
    {"key": "female_exec", "label": "Female Office", "icon": "person-vcard-fill",     "gender": "female"},
    {"key": "developer",   "label": "Admin",                "icon": "person-workspace",      "gender": "other"},
    {"key": "neutral",     "label": "Default",              "icon": "person-circle",         "gender": "other"},
)
AVATAR_ICON_MAP = {option["key"]: option["icon"] for option in AVATAR_OPTIONS}
AVATAR_KEYS = set(AVATAR_ICON_MAP.keys())

SUPPORTED_LANGUAGES = {
    "en": {"name": "English", "dir": "ltr"},
    "sw": {"name": "Swahili", "dir": "ltr"},
    "fr": {"name": "French", "dir": "ltr"},
    "ar": {"name": "Arabic", "dir": "rtl"},
}

SETTINGS_TRANSLATIONS = {
    "en": {
        "settings_title": "System Settings",
        "language": "Language",
        "language_help": "Choose your preferred display language.",
        "choose_language": "Choose language",
        "appearance": "Appearance",
        "appearance_help": "Switch between light mode and dark mode.",
        "dark_mode": "Dark mode",
        "apply_theme": "Apply Theme",
        "related_pages": "Related Pages",
    },
    "sw": {
        "settings_title": "Mipangilio ya Mfumo",
        "language": "Lugha",
        "language_help": "Chagua lugha unayopendelea kwenye mfumo.",
        "choose_language": "Chagua lugha",
        "appearance": "Muonekano",
        "appearance_help": "Badilisha kati ya hali ya mwanga na hali ya giza.",
        "dark_mode": "Hali ya giza",
        "apply_theme": "Tumia Muonekano",
        "related_pages": "Kurasa Zinazohusiana",
    },
    "fr": {
        "settings_title": "Parametres du systeme",
        "language": "Langue",
        "language_help": "Choisissez votre langue d'affichage preferee.",
        "choose_language": "Choisir la langue",
        "appearance": "Apparence",
        "appearance_help": "Basculer entre le mode clair et le mode sombre.",
        "dark_mode": "Mode sombre",
        "apply_theme": "Appliquer le theme",
        "related_pages": "Pages associees",
    },
    "ar": {
        "settings_title": "إعدادات النظام",
        "language": "اللغة",
        "language_help": "اختر لغة العرض المفضلة لديك.",
        "choose_language": "اختر اللغة",
        "appearance": "المظهر",
        "appearance_help": "التبديل بين الوضع الفاتح والوضع الداكن.",
        "dark_mode": "الوضع الداكن",
        "apply_theme": "تطبيق المظهر",
        "related_pages": "صفحات ذات صلة",
    },
}

# Technician PM Sections (full)
TECHNICIAN_PM_SECTIONS = [
    {
        "title": "ATTRIBUTE",
        "fields": [
            "Activity", "Activity Date", "Activity Time", "Access Ref", "Site Number", "Site Name",
            "Site Type", "Purpose of Visit", "Confirm Personal Protective Equipment", "Site Clean",
            "Security Guard Present?", "Comment"
        ]
    },
    {
        "title": "GENERATOR CHECKS",
        "fields": [
            "Number of fuel Tanks", "Tank Type (Base/ Standalone)", "Diesel Tank Capacity (L)",
            "Diesel level (L)", "Is fuel sensor connected?", "Is fuel sensor functional?",
            "DG Manufacturer", "DG Serial Number", "DG Engine Serial Number", "DG Capacity (kVA)",
            "DG Hour Service Kit", "Date of Last Service", "DG Run Hour at Last Service",
            "Current DG Run Hours", "DG Battery on Site", "Is Battery on DG Working?",
            "Is DG oil filter replaced?", "Is DG fuel filter replaced?", "Is DG air filter replaced?",
            "Liters of Engine Oil Used", "Any Engine Oil Topped up other than DG Service Oil in Liters",
            "Signs of leakage along the DG fuel supply line", "If yes, has the leak been fixed?",
            "Is DG Fan Belt in good condition", "Has Coolant Been Added?", "Amount of Coolant Added in Liters",
            "DG Controller Manufacturer", "DG Controller Serial Number", "DG Controller Model Number",
            "Is controller in Auto mode?"
        ]
    },
    {
        "title": "ATS/ AUTOMATION CHECKS",
        "fields": [
            "ATS Installed?", "Is ATS Working?", "Has ATS functionality been tested by simulating a mains failure",
            "Is Site Connected to Grid?", "Was grid available during site visit?", "Any grid faults identified? Share.",
            "Meter Type (Post/ pre-paid)", "Grid Meter Number", "Grid Meter Reading", "Is Grid Meter Working?",
            "Connection Type: (Single or Three Phase)", "Grid supply current - Ph3 (A)"
        ]
    },
    {
        "title": "DC SYSTEMS: RECTIFIER CHECKS",
        "fields": [
            "Number of Rectifiers Installed", "DC Location: (Indoor/ Outdoor)", "Rectifier Type",
            "Rectifier Serial Number", "Rectifier Model Number", "DC Loads (A)", "Rectifier Module Capacity",
            "System Voltage", "No of slots available in the rectifier", "Are rectifier modules cleared of dust?",
            "No. of Rectifiers Modules Present", "No of Working Rectifier Modules", "No. of Faulty Rectifier Modules"
        ]
    },
    {
        "title": "DC SYSTEMS: BATTERY CHECKS",
        "fields": [
            "Are Batteries Installed?", "Battery Bank Location (Indoor /outdoor)", "Battery Manufacturer",
            "Battery Capacity", "Number of Battery strings", "Battery Condition", "Number of batteries per strings in the Bank",
            "Total Number of Batteries at site", "Number of Battery Strings Connected", "Approximate Battery Backup Time",
            "Is Hybrid Installed?", "Type of Hybrid Installed", "Is Hybrid Working?", "Hybrid parameters checked?",
            "Is battery current limit set?", "Are all alarms wires connected?", "Is battery capacity set as per installed battery?",
            "Ensure all terminations and connections are tightened"
        ]
    },
    {
        "title": "EARTHING CHECKS",
        "fields": [
            "Earthing Resistance - Generator", "Earthing Resistance - ATS", "Earthing Resistance - ACDB",
            "Earthing Resistance - Rectifier", "Earthing Resistance - DCDB", "Earthing Resistance - RMS Unit",
            "Earthing Resistance - Tenant Equipment", "Earthing Resistance - Tower Leg", "Earthing Resistance - Fence"
        ]
    },
    {
        "title": "EXTERNAL ALARMS CHECKS",
        "fields": ["Are External Alarms connected", "Have Alarms been tested with NOC?"]
    },
    {
        "title": "SHELTER STATUS",
        "fields": [
            "No of Shelter Number", "Visible signs of leakage", "Openings/gaps in walls or roof",
            "If yes, seal all openings in wall with approvals", "No of  Aircons in Shelter",
            "Are all Aircons in Shelter Functional", "Door Status", "Floor Status", "Roof Status",
            "Are all Shelter Lighting Working?"
        ]
    },
    {
        "title": "SITE CLOSURE AFTER WORKS",
        "fields": [
            "Have you logged out with Airtel NOC", "Is Gate Closed on Exit",
            "Is gate not closed because someone else is on site?"
        ]
    }
]

TECHNICIAN_PHOTO_FIELDS = [
    {"key": "site_signage_board", "label": "Site Signage Board"},
    {"key": "dg_closed_doors", "label": "Full view of DG Appearance, Closed doors"},
    {"key": "dg_open_doors", "label": "Full view DG Photo when Canopy doors open"},
    {"key": "dg_run_hours_photo", "label": "DG Run Hours Photo"},
    {"key": "dg_serial_number_photo", "label": "DG Serial Number Photo"},
    {"key": "clamped_ac_loads_photo", "label": "Clamped AC Loads Photo"},
    {"key": "starter_battery_photo", "label": "Starter Battery Photo"},
    {"key": "dg_engine_serial_number_photo", "label": "DG Engine Serial Number Photo"},
    {"key": "dg_battery_voltage_photo", "label": "DG battery Voltage Photo (When AC power off)"},
    {"key": "fixed_fan_belt_photo", "label": "Fixed Fan Belt Photo"},
    {"key": "old_fan_belt_photo", "label": "Old Fan Belt before replacement Photo"},
    {"key": "new_fan_belt_photo", "label": "New Fan Belt After Replacement Photo"},
    {"key": "coolant_poured_photo", "label": "Radiator Coolant been poured Photo"},
    {"key": "old_oil_filter_photo", "label": "Old Oil Filter on DG Photo"},
    {"key": "new_oil_filter_photo", "label": "New Oil Filter on DG Photo"},
    {"key": "old_fuel_filter_photo", "label": "Old Fuel Filter Photo"},
    {"key": "new_fuel_filter_photo", "label": "New Fuel Filter Photo"},
    {"key": "old_air_filter_photo", "label": "Old Air Filter"},
    {"key": "new_air_filter_photo", "label": "New Air Filter"},
    {"key": "updated_dg_service_card", "label": "Updated DG Service Card Photo"},
    {"key": "updated_fueling_card", "label": "Updated Fueling Card Photo"},
    {"key": "rectifier_settings_1", "label": "Rectifier settings Photos_1"},
    {"key": "rectifier_settings_2", "label": "Rectifier settings Photos_2"},
    {"key": "rectifier_settings_3", "label": "Rectifier settings Photos_3"},
    {"key": "rectifier_settings_4", "label": "Rectifier settings Photos_4"},
    {"key": "fuel_leakage_signs", "label": "Signs of Fuel leakage along the DG"},
    {"key": "ats_installed_photo", "label": "ATS Installed Photo"},
    {"key": "acdb_photo", "label": "ACDB Photo"},
    {"key": "dg_v_ph1_ph2", "label": "DG Supply Voltage - Ph1 to Ph2 (V) Photo"},
    {"key": "dg_v_ph1_ph3", "label": "DG Supply Voltage - Ph1 to Ph3 (V) Photo"},
    {"key": "dg_v_ph2_ph3", "label": "DG Supply Voltage - Ph2 to Ph3 (V) Photo"},
    {"key": "dg_v_ph1_n", "label": "DG Supply Voltage - Ph1 to Neutral (V) Photo"},
    {"key": "dg_v_ph2_n", "label": "DG Supply Voltage - Ph2 to Neutral (V) Photo"},
    {"key": "dg_v_ph3_n", "label": "DG Supply Voltage - Ph3 to Neutral (V) Photo"},
    {"key": "dg_i_ph1", "label": "DG supply current - Ph1 Current (A) Photo"},
    {"key": "dg_i_ph2", "label": "DG supply current - Ph2 Current (A) Photo"},
    {"key": "dg_i_ph3", "label": "DG supply current - Ph3 Current (A) Photo"},
    {"key": "rectifier_closed", "label": "Full View Rectifier Cabinet Photo (CLOSED)"},
    {"key": "rectifier_open", "label": "Full View Rectifier Cabinet Photo (OPEN)"},
    {"key": "rectifier_controller", "label": "Rectifier Controller Photo"},
    {"key": "rectifier_slots", "label": "Number of rectifier module slots Photo"},
    {"key": "rectifier_cabinet_serial", "label": "Rectifier Cabinet Serial Number"},
    {"key": "rectifier_controller_serial", "label": "Rectifier Controller Serial Number"},
    {"key": "cleaning_modules", "label": "Photo when cleaning modules"},
    {"key": "system_voltage_photo", "label": "System Voltage Photo"},
    {"key": "hybrid_system_site", "label": "Hybrid System at Site"},
    {"key": "battery_bank_full_view", "label": "Battery Bank Full View Photo"},
    {"key": "battery_capacity_photo", "label": "Battery Capacity Photo"},
    {"key": "tower_full_photo", "label": "Tower Full Photo"},
    {"key": "tower_legs", "label": "Tower Legs 1,2,3,4"},
    {"key": "rectifier_photo", "label": "Rectifier"},
    {"key": "acdb_dcdb", "label": "ACDB, DCDB"},
    {"key": "dg_photo", "label": "DG"},
    {"key": "tenant_equipment", "label": "Tenant Equipment"},
    {"key": "shelter_interior", "label": "Shelter Interior After Cleaning"},
    {"key": "shelter_lighting", "label": "Shelter Lighting"},
    {"key": "shelter_door_status", "label": "Shelter Door status"},
    {"key": "bbs_door_status", "label": "BBS Door status"},
    {"key": "unused_equipment", "label": "Any unused Equipment on site"},
    {"key": "site_perimeter", "label": "Site Perimeter"},
    {"key": "site_janitorial", "label": "Site Janitorial"},
    {"key": "gate_lock", "label": "Gate Lock"}
]

# ============================================================================
# Helper Functions (all original, kept intact)
# ============================================================================

def _check_image_magic(stream) -> bool:
    header = stream.read(16)
    stream.seek(0)
    if any(header.startswith(magic) for magic, _ in _IMAGE_MAGIC):
        return True
    return len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP"

def _is_valid_image_file_path(file_path):
    try:
        with open(file_path, "rb") as fh:
            header = fh.read(16)
    except Exception:
        return False
    is_magic_ok = any(header.startswith(magic) for magic, _ in _IMAGE_MAGIC) or (
        len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    )
    if not is_magic_ok:
        return False
    if Image is None:
        return True
    try:
        with Image.open(file_path) as img:
            img.verify()
        return True
    except Exception:
        # Pillow may not support some formats (e.g. WebP if not compiled with libwebp).
        # Accept file if magic bytes are valid but PIL verification fails.
        return True

def _stream_size_bytes(stream):
    try:
        current = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(current)
        return size
    except Exception:
        return None

def get_record_or_404(model, record_id):
    record = db.session.get(model, record_id)
    if record is None:
        abort(404)
    return record

def load_site_master():
    current_dir = os.path.abspath(os.path.dirname(__file__))
    candidate_paths = [
        os.path.join(current_dir, os.pardir, "config", "site_master.json"),
        os.path.join(current_dir, "config", "site_master.json"),
    ]
    path = None
    for candidate in candidate_paths:
        candidate = os.path.abspath(candidate)
        if os.path.isfile(candidate):
            path = candidate
            break

    if path is None:
        return []

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    sites = payload.get("sites", []) if isinstance(payload, dict) else []
    cleaned = []
    seen = set()
    for site in sites:
        if not isinstance(site, dict):
            continue
        site_id = (site.get("site_id") or "").strip().upper()
        site_name = (site.get("site_name") or "").strip()
        if not site_id or site_id in seen:
            continue
        seen.add(site_id)
        item = dict(site)
        item["site_id"] = site_id
        item["site_name"] = site_name
        cleaned.append(item)
    return cleaned

def site_master_options():
    return [
        {
            "site_id": item.get("site_id", ""),
            "site_name": item.get("site_name", ""),
            "site_type": item.get("site_type", ""),
            "region": item.get("region", ""),
            "area": item.get("area", ""),
            "open_issue_count": item.get("open_issue_count", 0),
        }
        for item in load_site_master()
    ]

def resolve_avatar_key(raw_avatar_key, raw_gender):
    avatar_key = (raw_avatar_key or "").strip().lower()
    if avatar_key in AVATAR_KEYS:
        return avatar_key
    _legacy = {"male_tech": "technician", "female_tech": "female_exec"}
    if avatar_key in _legacy:
        return _legacy[avatar_key]
    normalized_gender = (raw_gender or "").strip().lower()
    if normalized_gender in {"female", "f"}:
        return "female_exec"
    if normalized_gender in {"male", "m"}:
        return "technician"
    return "neutral"



def get_public_base_url():
    try:
        tunnel_url_file = os.path.join(os.path.dirname(__file__), "tools", "tunnel_url.txt")
        if os.path.isfile(tunnel_url_file):
            tunnel_base = open(tunnel_url_file, encoding="utf-8").read().strip().rstrip("/")
            if tunnel_base:
                if "://" not in tunnel_base:
                    tunnel_base = "https://" + tunnel_base
                return tunnel_base.rstrip("/")
    except Exception:
        pass
    configured_base = ""
    if has_app_context():
        configured_base = (current_app.config.get("PUBLIC_BASE_URL") or "").strip()
    if not configured_base:
        configured_base = os.getenv("PUBLIC_BASE_URL", "").strip()
    if configured_base:
        if "//" not in configured_base:
            configured_base = "https://" + configured_base
        return configured_base.rstrip("/")
    forwarded_host = (request.headers.get("X-Forwarded-Host", "") or "").split(",")[0].strip()
    forwarded_proto = (request.headers.get("X-Forwarded-Proto", "") or "").split(",")[0].strip()
    if forwarded_host:
        scheme = forwarded_proto or request.scheme or "https"
        return f"{scheme}://{forwarded_host}".rstrip("/")
    host_url = request.host_url.rstrip("/")
    try:
        parsed = urlparse(host_url)
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "127.0.0.1", "::1"}:
            import socket
            lan_ip = ""
            try:
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                probe.connect(("8.8.8.8", 80))
                lan_ip = probe.getsockname()[0]
                probe.close()
            except Exception:
                pass
            if not lan_ip:
                lan_ip = socket.gethostbyname(socket.gethostname()) or ""
            if lan_ip and not lan_ip.startswith("127."):
                port = parsed.port
                port_suffix = f":{port}" if port and port not in {80, 443} else ""
                return f"{parsed.scheme}://{lan_ip}{port_suffix}"
    except Exception:
        pass
    return host_url

def normalize_public_base_url(raw_url, *, allow_http=True):
    value = (raw_url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if parsed.scheme == "http" and not allow_http:
        return ""
    if not parsed.netloc:
        return ""
    normalized_path = (parsed.path or "").rstrip("/")
    for login_suffix in ("/technician/login", "/staff/login", "/developer/login", "/login"):
        if normalized_path.lower().endswith(login_suffix):
            normalized_path = normalized_path[: -len(login_suffix)]
            break
    return f"{parsed.scheme}://{parsed.netloc}{normalized_path}".rstrip("/")

def build_share_login_url(base_url):
    normalized = normalize_public_base_url(base_url)
    if not normalized:
        return ""
    login_path = (url_for('technician_login') or "").rstrip("/") or "/"
    return f"{normalized}{login_path}"


def _log_share_context_resolution(source, public_base_url):
    request_host = request.host_url if has_request_context() else None
    logger = current_app.logger if has_app_context() else logging.getLogger(__name__)
    if source == "none":
        logger.warning(
            "Share context resolution failed: no public or local base URL candidates found; request_host=%r",
            request_host,
        )
    elif source not in {"preferred", "request"}:
        logger.warning(
            "Share context fallback selected: source=%s public_base_url=%r request_host=%r",
            source,
            public_base_url,
            request_host,
        )


def resolve_share_context(preferred_base_url=None):
    normalized_preferred = normalize_public_base_url(preferred_base_url)
    if normalized_preferred:
        return {
            "public_base_url": normalized_preferred,
            "login_url": build_share_login_url(normalized_preferred),
            "source": "preferred",
            "is_public": is_public_share_base(normalized_preferred),
        }
    tunnel_url_file = os.path.join(os.path.dirname(__file__), "tools", "tunnel_url.txt")
    candidates = []
    request_base = normalize_public_base_url(request.host_url if has_request_context() else "")
    if request_base and is_public_share_base(request_base):
        candidates.append(("request", request_base))
    try:
        if os.path.isfile(tunnel_url_file):
            tunnel_base = normalize_public_base_url(open(tunnel_url_file, encoding="utf-8").read().strip())
            if tunnel_base:
                candidates.append(("tunnel", tunnel_base))
    except Exception:
        pass
    configured_base_raw = ""
    if has_app_context():
        configured_base_raw = current_app.config.get("PUBLIC_BASE_URL", "")
    if not configured_base_raw:
        configured_base_raw = os.getenv("PUBLIC_BASE_URL", "")
    configured_base = normalize_public_base_url(configured_base_raw)
    if configured_base:
        candidates.append(("env", configured_base))
    inferred_base = normalize_public_base_url(get_public_base_url())
    if inferred_base:
        candidates.append(("runtime", inferred_base))
    seen = set()
    best_local = ""
    best_local_source = "none"
    for source, base in candidates:
        if not base or base in seen:
            continue
        seen.add(base)
        if is_public_share_base(base):
            _log_share_context_resolution(source, base)
            return {
                "public_base_url": base,
                "login_url": build_share_login_url(base),
                "source": source,
                "is_public": True,
            }
        if not best_local:
            best_local = base
            best_local_source = source
    _log_share_context_resolution(best_local_source, best_local)
    return {
        "public_base_url": best_local,
        "login_url": build_share_login_url(best_local) if best_local else "",
        "source": best_local_source,
        "is_public": is_public_share_base(best_local),
    }





def get_dashboard_menu_for_role(role):
    return ROLE_DASHBOARD_MENU.get(normalize_role(role), [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Notifications", "endpoint": "notifications"},
        {"label": "Settings", "endpoint": "settings_page"},
    ])

def allowed_login_roles(selected_role):
    selected_role = normalize_role(selected_role)
    role_map = DEFAULT_ROLE_ACCESS_MATRIX
    if has_app_context():
        configured = current_app.config.get("ROLE_ACCESS_MATRIX")
        if isinstance(configured, dict):
            role_map = normalize_role_access_matrix(configured)
    return set(role_map.get(selected_role, []))

def normalize_role_access_matrix(raw_matrix):
    normalized = {}
    role_order = {role: idx for idx, role in enumerate(VALID_ACCOUNT_ROLES)}
    for matrix_key in LOGIN_MATRIX_KEYS:
        values = raw_matrix.get(matrix_key, []) if isinstance(raw_matrix, dict) else []
        if not isinstance(values, (list, tuple, set)):
            values = []
        cleaned = []
        for value in values:
            role = normalize_role(value)
            if role in VALID_ACCOUNT_ROLES and role not in cleaned:
                cleaned.append(role)
        if not cleaned:
            cleaned = list(DEFAULT_ROLE_ACCESS_MATRIX[matrix_key])
        normalized[matrix_key] = sorted(cleaned, key=lambda item: role_order[item])
    return normalized

def _coerce_policy_hours(value, default, minimum=1, maximum=168):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))

def normalize_sla_policy_config(raw_policy=None):
    raw_policy = raw_policy if isinstance(raw_policy, dict) else {}
    standard_hours = _coerce_policy_hours(raw_policy.get("standard_hours"), SLA_HOURS_STANDARD)
    critical_hours = _coerce_policy_hours(raw_policy.get("critical_hours"), SLA_HOURS_CRITICAL)
    due_soon_hours = _coerce_policy_hours(
        raw_policy.get("due_soon_hours"),
        SLA_DUE_SOON_HOURS,
        minimum=1,
        maximum=min(72, max(1, min(standard_hours, critical_hours))),
    )
    return {
        "enabled": bool(raw_policy.get("enabled", True)),
        "standard_hours": standard_hours,
        "critical_hours": critical_hours,
        "due_soon_hours": due_soon_hours,
        "policy_agreed": bool(raw_policy.get("policy_agreed", False)),
        "updated_at": raw_policy.get("updated_at") or "",
        "updated_by": raw_policy.get("updated_by") or "System Default",
        "updated_role": raw_policy.get("updated_role") or "system",
        "source": raw_policy.get("source") or "default",
    }

def build_sla_deadline_from_policy(*, activity_type: str, is_critical: bool, now_value: datetime, policy: dict | None):
    normalized_policy = normalize_sla_policy_config(policy)
    if not normalized_policy["enabled"]:
        return None
    try:
        local_standard = int(current_app.config.get("SLA_STANDARD_HOURS", normalized_policy["standard_hours"]))
        local_critical = int(current_app.config.get("SLA_CRITICAL_HOURS", normalized_policy["critical_hours"]))
        local_due_soon = int(current_app.config.get("SLA_DUE_SOON_HOURS", normalized_policy["due_soon_hours"]))
    except RuntimeError:
        local_standard = normalized_policy["standard_hours"]
        local_critical = normalized_policy["critical_hours"]
        local_due_soon = normalized_policy["due_soon_hours"]
    deadline_hours = local_critical if is_critical or activity_type == "rca" else local_standard
    return now_value + timedelta(hours=deadline_hours)


_HOLIDAYS_CONFIG = {
    2024: [
        {"date": "2024-01-01", "name": "New Year's Day"},
        {"date": "2024-02-16", "name": "Archbishop Janani Luwum Day"},
        {"date": "2024-03-08", "name": "International Women's Day"},
        {"date": "2024-04-05", "name": "Good Friday"},
        {"date": "2024-04-08", "name": "Easter Monday"},
        {"date": "2024-05-01", "name": "Labour Day"},
        {"date": "2024-06-03", "name": "Uganda Martyrs' Day"},
        {"date": "2024-06-09", "name": "National Heroes' Day"},
        {"date": "2024-10-09", "name": "Independence Day"},
        {"date": "2024-12-25", "name": "Christmas Day"},
        {"date": "2024-12-26", "name": "Boxing Day"},
    ],
    2025: [
        {"date": "2025-01-01", "name": "New Year's Day"},
        {"date": "2025-02-16", "name": "Archbishop Janani Luwum Day"},
        {"date": "2025-03-08", "name": "International Women's Day"},
        {"date": "2025-04-18", "name": "Good Friday"},
        {"date": "2025-04-21", "name": "Easter Monday"},
        {"date": "2025-05-01", "name": "Labour Day"},
        {"date": "2025-06-03", "name": "Uganda Martyrs' Day"},
        {"date": "2025-06-09", "name": "National Heroes' Day"},
        {"date": "2025-10-09", "name": "Independence Day"},
        {"date": "2025-12-25", "name": "Christmas Day"},
        {"date": "2025-12-26", "name": "Boxing Day"},
    ],
    2026: [
        {"date": "2026-01-01", "name": "New Year's Day"},
        {"date": "2026-01-26", "name": "NRM Liberation Day"},
        {"date": "2026-02-16", "name": "Archbishop Janani Luwum Day"},
        {"date": "2026-03-08", "name": "International Women's Day"},
        {"date": "2026-04-03", "name": "Good Friday"},
        {"date": "2026-04-06", "name": "Easter Monday"},
        {"date": "2026-05-01", "name": "Labour Day"},
        {"date": "2026-06-03", "name": "Uganda Martyrs' Day"},
        {"date": "2026-06-09", "name": "National Heroes' Day"},
        {"date": "2026-10-09", "name": "Independence Day"},
        {"date": "2026-12-25", "name": "Christmas Day"},
        {"date": "2026-12-26", "name": "Boxing Day"},
    ],
}

def get_public_holidays():
    current_year = datetime.now(timezone.utc).year
    return _HOLIDAYS_CONFIG.get(current_year, [])

def slugify_label(label):
    cleaned = [ch.lower() if ch.isalnum() else "_" for ch in label]
    slug = "".join(cleaned)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")

def is_yes_no_label(label):
    YES_NO_HINTS = ("is ", "has ", "have ", "are ", "was ", "confirm", "working", "present", "connected")
    value = label.strip().lower()
    return any(value.startswith(prefix) or prefix in value for prefix in YES_NO_HINTS)

def save_signature_image(signature_data, upload_folder):
    if not signature_data or not signature_data.startswith("data:image/png;base64,"):
        return None
    payload = signature_data.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(payload)
    except Exception:
        return None
    if not image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return None
    filename = f"signature_{uuid.uuid4().hex}.png"
    file_path = os.path.join(upload_folder, filename)
    with open(file_path, "wb") as out_file:
        out_file.write(image_bytes)
    return filename

def describe_uploaded_photo(field_label, filename):
    safe_label = (field_label or "Uploaded photo").strip()
    raw_name = (filename or "").strip()
    lowered = raw_name.lower()
    source_hint = "Uploaded camera image"
    if "screenshot" in lowered:
        source_hint = "Mobile screenshot"
    elif "whatsapp" in lowered:
        source_hint = "WhatsApp image"
    context_hint = f"Evidence for {safe_label}."
    if any(token in lowered for token in ("chrome", "pdf", "download", "zoom", "viewer")):
        context_hint = f"Evidence for {safe_label}; filename suggests a screen capture of a document or app view."
    return f"{source_hint}. {context_hint}"

PHOTO_LIBRARY_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DEFAULT_PHOTO_LIBRARY_CONTROLS = {
    "include_screenshots": True,
    "allow_import": True,
    "max_scan_limit": 96,
}

def normalize_photo_library_controls(raw_controls):
    controls = dict(DEFAULT_PHOTO_LIBRARY_CONTROLS)
    if not isinstance(raw_controls, dict):
        return controls
    include_screenshots = raw_controls.get("include_screenshots")
    if isinstance(include_screenshots, bool):
        controls["include_screenshots"] = include_screenshots
    allow_import = raw_controls.get("allow_import")
    if isinstance(allow_import, bool):
        controls["allow_import"] = allow_import
    try:
        max_scan_limit = int(raw_controls.get("max_scan_limit", controls["max_scan_limit"]))
    except (TypeError, ValueError):
        max_scan_limit = controls["max_scan_limit"]
    controls["max_scan_limit"] = min(max(max_scan_limit, 12), 200)
    return controls

def describe_monitored_image(file_path, filename):
    raw_name = (filename or "").strip()
    lowered = raw_name.lower()
    if not _is_valid_image_file_path(file_path):
        return "File failed image validation checks and may be corrupted or not an image."
    width = None
    height = None
    fmt = "unknown"
    mode = "unknown"
    if Image is not None:
        try:
            with Image.open(file_path) as img:
                width, height = img.size
                fmt = (img.format or "unknown").upper()
                mode = (img.mode or "unknown").upper()
        except Exception:
            pass
    if width and height:
        megapixels = round((width * height) / 1_000_000, 2)
        orientation = "portrait" if height > width else "landscape"
        metadata_line = f"{fmt} image, {width}x{height}px ({megapixels} MP), {orientation}, mode {mode}."
    else:
        metadata_line = "Image metadata could not be read fully; file passed basic validation checks."
    screenshot_signals = ["screenshot", "chrome", "pdf", "download", "viewer", "zoom"]
    if any(token in lowered for token in screenshot_signals):
        return metadata_line + " Likely screenshot or document-view capture based on filename cues."
    if "whatsapp image" in lowered:
        return metadata_line + " WhatsApp-exported image; verify whether it is a camera photo or forwarded screenshot."
    if any(token in lowered for token in ("tower", "battery", "rectifier", "dg", "generator", "site", "acdb")):
        return metadata_line + " Filename suggests field maintenance evidence."
    return metadata_line + " Monitored image from the photo source."

def collect_technician_form_details(form_data):
    lines = []
    header_pairs = [
        ("Client", "AIRTEL UGANDA"),
        ("Vendor", "SOLITON TELMEC (U) LTD"),
        ("Activity Name", "AIRTEL UG Planned Preventive Maintenance Form"),
        ("Submitted By", form_data.get("submitted_by") or ""),
        ("Activity Start", form_data.get("activity_start") or ""),
        ("Activity End", form_data.get("activity_end") or ""),
        ("Validation Comments (By Technician)", form_data.get("validation_comments") or ""),
    ]
    lines.append("PM FORM HEADER")
    for label, value in header_pairs:
        lines.append(f"{label}: {value}")
    for section in TECHNICIAN_PM_SECTIONS:
        lines.append("")
        lines.append(section["title"])
        for label in section["fields"]:
            key = f"field_{slugify_label(label)}"
            lines.append(f"- {label}: {form_data.get(key, '')}")
    return "\n".join(lines)

# Extracted parsing, pdf, and analysis helpers into separate modules
from pm_app.legacy_parsing import *
from pm_app.legacy_pdf import *
from pm_app.legacy_analysis import *

