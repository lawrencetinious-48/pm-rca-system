# Utility functions for the app

import os
import uuid
import base64
import secrets
import hmac
import ipaddress
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from flask import current_app, has_app_context, session, request

from app_pkg.constants import VALID_ACCOUNT_ROLES, ADMIN_ROLES, DESK_ROLES, TECHNICIAN_ROLES, LOGIN_MATRIX_KEYS, DEFAULT_ROLE_ACCESS_MATRIX, SLA_HOURS_STANDARD, SLA_HOURS_CRITICAL, SLA_DUE_SOON_HOURS, ROLE_DASHBOARD_MENU, ROLE_UID_PREFIX, ROLE_EQUIVALENTS

def normalize_role(role: str) -> str:
    """Normalize role string to lowercase with underscores and map legacy aliases."""
    if not role:
        return ""
    normalized = role.strip().lower().replace(" ", "_").replace("-", "_")
    return ROLE_EQUIVALENTS.get(normalized, normalized)

def generate_uid(role: str) -> str:
    """Generate a unique user ID with role prefix."""
    role_prefix = ROLE_UID_PREFIX.get(normalize_role(role), "UNK")
    return f"{role_prefix}-{uuid.uuid4().hex[:8].upper()}"

def csrf_token_is_valid() -> bool:
    """Validate CSRF token from form against session."""
    if not has_app_context():
        return False
    token_from_form = request.form.get("csrf_token") or request.form.get("login_csrf_token")
    token_from_session = session.get("csrf_token")
    if not token_from_form or not token_from_session:
        return False
    return hmac.compare_digest(token_from_form, token_from_session)
    
def get_csrf_token() -> str:
    """Get or generate CSRF token for session."""
    if not has_app_context():
        return secrets.token_urlsafe(32)
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]

def is_public_share_base(base_url):
    if not base_url:
        return False
    try:
        host = (urlparse(base_url).hostname or "").strip().lower()
    except Exception:
        return False
    if not host or host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return False
    try:
        host_ip = ipaddress.ip_address(host)
        return not (
            host_ip.is_private
            or host_ip.is_loopback
            or host_ip.is_link_local
            or host_ip.is_multicast
            or host_ip.is_reserved
            or host_ip.is_unspecified
        )
    except ValueError:
        return True

def is_admin_role(role):
    return normalize_role(role) in ADMIN_ROLES

def is_desk_role(role):
    return normalize_role(role) in DESK_ROLES

def is_technician_role(role):
    return normalize_role(role) in TECHNICIAN_ROLES

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
    except RuntimeError:
        local_standard = normalized_policy["standard_hours"]
        local_critical = normalized_policy["critical_hours"]
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
    controls["include_screenshots"] = bool(raw_controls.get("include_screenshots", controls["include_screenshots"]))
    controls["allow_import"] = bool(raw_controls.get("allow_import", controls["allow_import"]))
    controls["max_scan_limit"] = max(12, min(200, int(raw_controls.get("max_scan_limit", controls["max_scan_limit"]))))
    return controls

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

# Need to import ROLE_UID_PREFIX from constants
