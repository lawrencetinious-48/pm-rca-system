"""Security-focused test suite.

Covers:
- File-upload MIME validation (magic-byte check)
- Signature image validation
- CSRF enforcement on mutations
- Role-based access control on key routes
- API error format consistency
- Rate-limit header presence
"""
import io
import base64
import struct
import logging

import pytest
from werkzeug.security import generate_password_hash

from conftest import extract_hidden_input
from model import Activity, Message, User, UserSettings, db, utcnow_naive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _png_bytes(width: int = 1, height: int = 1) -> bytes:
    """Return a minimal but valid 1×1 PNG image as bytes."""
    import zlib

    def _chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    IHDR = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"\x00" + b"\x00\x00\x00" * width  # filter byte + RGB pixels
    IDAT = zlib.compress(raw)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", IHDR)
        + _chunk(b"IDAT", IDAT)
        + _chunk(b"IEND", b"")
    )


def _png_data_url(png: bytes | None = None) -> str:
    png = png or _png_bytes()
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _login_user(client, email, password, role="developer"):
    resp = client.get("/login")
    token = extract_hidden_input(resp.get_data(as_text=True), "login_csrf_token")
    client.post(
        "/login",
        data={"email": email, "password": password, "account_type": role, "login_csrf_token": token},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def staff_user(app):
    with app.app_context():
        u = User(
            email="staff@example.com",
            full_name="Staff User",
            role="staff",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(u)
        db.session.commit()
    return {"email": "staff@example.com", "password": "Password123!"}

@pytest.fixture()
def tech_user(app):
    with app.app_context():
        u = User(
            email="tech@example.com",
            full_name="Tech User",
            role="technician",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(u)
        db.session.commit()
    return {"email": "tech@example.com", "password": "Password123!"}


@pytest.fixture()
def manager_user(app):
    with app.app_context():
        u = User(
            email="manager@example.com",
            full_name="Manager User",
            role="manager",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(u)
        db.session.commit()
    return {"email": "manager@example.com", "password": "Password123!"}


# ---------------------------------------------------------------------------
# Upload / magic-byte validation
# ---------------------------------------------------------------------------

def test_file_upload_rejects_non_image_extension(app, client, tech_user, login_as_developer):
    """Magic-byte validator should reject non-image payloads."""
    from app import _check_image_magic

    fake_stream = io.BytesIO(b"not-an-image")
    assert _check_image_magic(fake_stream) is False


def test_signature_validation_rejects_invalid_base64(app, writable_temp_dir):
    """save_signature_image must return None for a corrupt payload."""
    from app import save_signature_image
    result = save_signature_image("data:image/png;base64,NOT_VALID_BASE64!!!", str(writable_temp_dir))
    assert result is None


def test_signature_validation_rejects_wrong_magic_bytes(app, writable_temp_dir):
    """save_signature_image must reject a valid base64 payload that isn't PNG."""
    from app import save_signature_image
    # JPEG magic bytes wrapped in a PNG data-URL
    fake = "data:image/png;base64," + base64.b64encode(b"\xff\xd8\xff\xe0fake").decode()
    result = save_signature_image(fake, str(writable_temp_dir))
    assert result is None


def test_signature_validation_accepts_real_png(app, writable_temp_dir):
    """save_signature_image must accept a genuine PNG payload."""
    from app import save_signature_image
    data_url = _png_data_url()
    result = save_signature_image(data_url, str(writable_temp_dir))
    assert result is not None
    assert result.endswith(".png")


# ---------------------------------------------------------------------------
# CSRF enforcement
# ---------------------------------------------------------------------------

def test_csrf_blocks_mutation_without_token(client, developer_user):
    _login_user(client, developer_user["email"], developer_user["password"])
    # POST without any CSRF token should be rejected.
    resp = client.post("/notifications/messages/send", data={"recipient_role": "all", "message_body": "hi"})
    # Should either redirect (flash) or return 400, not 200 OK with success.
    assert resp.status_code in {302, 400}


# ---------------------------------------------------------------------------
# Role-based access control
# ---------------------------------------------------------------------------

def test_technician_cannot_access_desk_activities(client, tech_user):
    _login_user(client, tech_user["email"], tech_user["password"], role="technician")
    resp = client.get("/desk/activities/", follow_redirects=False)
    assert resp.status_code == 403


def test_technician_cannot_access_admin_staff(client, tech_user):
    _login_user(client, tech_user["email"], tech_user["password"], role="technician")
    resp = client.get("/admin/staff/", follow_redirects=False)
    assert resp.status_code == 403


def test_staff_cannot_access_admin_staff(client, staff_user):
    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    resp = client.get("/admin/staff/", follow_redirects=False)
    assert resp.status_code == 403


def test_staff_can_access_consumables_page(client, staff_user):
    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    resp = client.get("/consumables/", follow_redirects=False)
    assert resp.status_code == 200


def test_manager_cannot_access_consumables_page(client, manager_user):
    _login_user(client, manager_user["email"], manager_user["password"], role="manager")
    resp = client.get("/consumables/", follow_redirects=False)
    assert resp.status_code == 403


def test_developer_cannot_access_consumables_page(client, developer_user):
    _login_user(client, developer_user["email"], developer_user["password"], role="developer")
    resp = client.get("/consumables/", follow_redirects=False)
    assert resp.status_code == 403


def test_staff_can_open_and_download_rca_tracker(client, staff_user):
    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    open_resp = client.get("/staff/rca-tracker/", follow_redirects=False)
    assert open_resp.status_code == 302 or open_resp.status_code == 200
    download_resp = client.get("/staff/rca-tracker/export", follow_redirects=False)
    assert download_resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in download_resp.headers.get("Content-Type", "")


def test_staff_can_access_staff_calendar(client, staff_user):
    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    resp = client.get("/staff/calendar/", follow_redirects=False)
    assert resp.status_code == 200


def test_developer_can_edit_user_profile(client, developer_user, staff_user, app):
    _login_user(client, developer_user["email"], developer_user["password"], role="developer")
    with app.app_context():
        target = User.query.filter_by(email=staff_user["email"]).first()
        assert target is not None
        user_id = target.id

    resp = client.post(
        f"/admin/staff/{user_id}/edit-profile",
        data={
            "email": "staff.updated@example.com",
            "uid": "STF-777",
            "first_name": "Updated",
            "last_name": "Staff",
            "region": "West",
            "gender": "female",
            "avatar_key": "female_exec",
            "support_desk": "NOC Desk",
            "site_operations_phone": "0312000000",
            "emergency_phone": "+256700000000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        updated = db.session.get(User, user_id)
        assert updated is not None
        assert updated.email == "staff.updated@example.com"
        assert updated.uid == "STF-777"
        assert updated.first_name == "Updated"
        assert updated.last_name == "Staff"
        assert updated.full_name == "Updated Staff"
        assert updated.region == "West"
        assert updated.gender == "female"
        assert updated.support_desk == "NOC Desk"
        assert updated.site_operations_phone == "0312000000"
        assert updated.emergency_phone == "+256700000000"

        settings = UserSettings.query.filter_by(user_id=updated.id).first()
        assert settings is not None
        assert settings.get_preferences().get("profile_avatar") == "female_exec"


def test_developer_profile_edit_rejects_duplicate_email(client, developer_user, staff_user, manager_user, app):
    _login_user(client, developer_user["email"], developer_user["password"], role="developer")
    with app.app_context():
        target = User.query.filter_by(email=staff_user["email"]).first()
        assert target is not None
        original_email = target.email
        user_id = target.id

    resp = client.post(
        f"/admin/staff/{user_id}/edit-profile",
        data={
            "email": manager_user["email"],
            "uid": "STF-101",
            "first_name": "Staff",
            "last_name": "User",
            "region": "Central",
            "gender": "male",
            "support_desk": "Desk",
            "site_operations_phone": "0312111111",
            "emergency_phone": "+256711111111",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        unchanged = db.session.get(User, user_id)
        assert unchanged is not None
        assert unchanged.email == original_email


def test_manager_dashboard_shows_sla_policy_card(client, manager_user):
    _login_user(client, manager_user["email"], manager_user["password"], role="manager")
    resp = client.get("/dashboard/", follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Desk SLA Policy" in body
    assert "Manage SLA Policy" in body


def test_anonymous_redirect_to_login(client):
    for path in ["/dashboard/", "/desk/activities/", "/admin/staff/", "/field/site-form/"]:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# API error format
# ---------------------------------------------------------------------------

def test_api_returns_consistent_error_on_forbidden(client, developer_user, staff_user):
    """Non-developer POSTing to consumables API should get a consistent error."""
    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    resp = client.post("/api/consumables/", json={"site_id": "X", "site_name": "Y", "description": "Z"})
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["status"] == "error"
    assert "code" in body
    assert "message" in body


def test_api_returns_consistent_error_on_missing_fields(client, developer_user, login_as_developer):
    """Missing required fields on POST /api/consumables/ should return structured error."""
    login_as_developer()
    resp = client.post("/api/consumables/", json={"site_id": "X"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["status"] == "error"
    assert body["code"] == "VALIDATION_ERROR"


def test_api_list_consumables_returns_status_ok(client, developer_user, login_as_developer):
    login_as_developer()
    resp = client.get("/api/consumables/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "items" in body


def test_delete_message_hides_only_for_current_user(client, app, developer_user, staff_user):
    with app.app_context():
        msg = Message(
            sender_email=staff_user["email"],
            sender_role="staff",
            recipient_role="all",
            recipient_email=None,
            body="Visibility test",
            created_at=utcnow_naive(),
        )
        db.session.add(msg)
        db.session.commit()
        msg_id = msg.id

    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    resp = client.post(f"/notifications/messages/{msg_id}/delete", data={}, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        still_exists = db.session.get(Message, msg_id)
        assert still_exists is not None
        settings = UserSettings.query.filter_by(user_id=User.query.filter_by(email=staff_user["email"]).first().id).first()
        assert settings is not None
        prefs = settings.get_preferences()
        hidden_ids = prefs.get("hidden_message_ids", []) if isinstance(prefs, dict) else []
        assert msg_id in hidden_ids


def test_create_app_honors_explicit_test_config_for_security_settings():
    from app import create_app

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SEED_SAMPLE_DATA": False,
            "SESSION_COOKIE_SECURE": True,
            "PREFERRED_URL_SCHEME": "https",
            "TRUSTED_PROXY_COUNT": 2,
        }
    )

    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_SECURE"] is True
    assert app.config["PREFERRED_URL_SCHEME"] == "https"


def test_developer_share_qr_endpoint_returns_svg_image(client, login_as_developer):
    login_as_developer()
    resp = client.get("/developer/share-qr.png?format=svg&url=https%3A%2F%2Fexample.com")
    assert resp.status_code == 200
    content_type = (resp.headers.get("Content-Type") or "").lower()
    assert "image/svg+xml" in content_type
    body = resp.get_data(as_text=True)
    assert "<svg" in body


def test_live_share_url_prefers_public_request_host(client, login_as_developer):
    login_as_developer(base_url="https://rca.example.com")
    resp = client.get(
        "/api/live-share-url",
        base_url="https://rca.example.com",
        headers={"X-Forwarded-Host": "rca.example.com", "X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["public_base_url"] == "https://rca.example.com"
    assert payload["login_url"].endswith("/technician/login")
    assert payload["is_public"] is True


def test_live_share_url_logs_fallback_for_env_base(client, app, login_as_developer, caplog):
    login_as_developer(base_url="http://localhost:5000")
    app.config["PUBLIC_BASE_URL"] = "https://rca.example.com"
    app.logger.propagate = True

    with caplog.at_level(logging.WARNING, logger=app.logger.name):
        resp = client.get("/api/live-share-url", base_url="http://localhost:5000")

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["public_base_url"] == "https://rca.example.com"
    assert "Share context fallback selected: source=env" in caplog.text


def test_normalize_public_base_url_strips_login_variants():
    from app import normalize_public_base_url

    assert normalize_public_base_url("https://rca.example.com/technician/login") == "https://rca.example.com"
    assert normalize_public_base_url("https://rca.example.com/login") == "https://rca.example.com"


# ---------------------------------------------------------------------------
# Risk scoring stored on Activity
# ---------------------------------------------------------------------------

def test_risk_score_constants_are_sensible():
    from app import HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD, SLA_DUE_SOON_HOURS
    assert 0 < MEDIUM_RISK_THRESHOLD < HIGH_RISK_THRESHOLD <= 100
    assert SLA_DUE_SOON_HOURS > 0


def test_is_public_share_base_rejects_non_routable_hosts():
    from app import is_public_share_base

    assert is_public_share_base("http://localhost:5001") is False
    assert is_public_share_base("http://127.0.0.1:5001") is False
    assert is_public_share_base("http://0.0.0.0:5001") is False
    assert is_public_share_base("http://192.168.1.10:5001") is False


def test_is_public_share_base_accepts_public_dns_name():
    from app import is_public_share_base

    assert is_public_share_base("https://example.com") is True


def test_classify_risk_level_boundaries():
    from app import classify_risk_level, HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD
    assert classify_risk_level(HIGH_RISK_THRESHOLD) == "High"
    assert classify_risk_level(HIGH_RISK_THRESHOLD - 1) == "Medium"
    assert classify_risk_level(MEDIUM_RISK_THRESHOLD) == "Medium"
    assert classify_risk_level(MEDIUM_RISK_THRESHOLD - 1) == "Low"
    assert classify_risk_level(0) == "Low"


def test_outage_signal_analysis_flags_site_down_as_critical():
    from app import analyze_outage_signals

    result = analyze_outage_signals("Site down with no service and multiple critical alarm events")
    assert result["risk_boost"] > 0
    assert "site_down" in result["matched_signals"]
    assert "OUTAGE_RESPONSE" in result["categories"]
    assert any("outage" in flag.lower() for flag in result["critical_flags"])


def test_outage_signal_analysis_scores_degraded_service_without_critical_flag():
    from app import analyze_outage_signals

    result = analyze_outage_signals("Intermittent packet loss and high latency observed")
    assert result["risk_boost"] > 0
    assert "service_degradation" in result["matched_signals"]
    assert result["critical_flags"] == []


def test_derive_sla_suggestion_returns_escalation_for_overdue_high_risk():
    from app import derive_sla_suggestion

    suggestion = derive_sla_suggestion("Overdue", "High")
    assert "SLA breached" in suggestion
    assert "escalate" in suggestion.lower()


def test_extract_recommendations_ignores_none_entries():
    from app import extract_recommendations_from_details

    details = """SMART INSIGHTS
Recommendations:
- None

PHOTO SPECIFICATIONS
- Battery: https://example.com/a.jpg
"""
    recs = extract_recommendations_from_details(details)
    assert recs == []


def test_overdue_high_risk_sla_escalation_does_not_crash_request(app, client, developer_user):
    """Regression test: overdue high-risk items should not trigger server errors."""
    from datetime import datetime, timedelta, timezone

    with app.app_context():
        tech = User(
            email="overdue-tech@example.com",
            full_name="Overdue Tech",
            role="technician",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(tech)
        db.session.add(
            Activity(
                activity_type="pm",
                details="Overdue high-risk PM",
                created_by=tech.email,
                risk_score=95,
                sla_deadline=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
                approved_at=None,
            )
        )
        db.session.commit()

    _login_user(client, developer_user["email"], developer_user["password"], role="developer")
    resp = client.get("/dashboard/", follow_redirects=False)
    assert resp.status_code in {200, 302}


def test_desk_activities_shows_fallback_sla_suggestion_for_legacy_rows(app, client, staff_user):
    from datetime import datetime, timedelta, timezone

    with app.app_context():
        tech = User(
            email="desk-legacy-tech@example.com",
            full_name="Desk Legacy Tech",
            role="technician",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(tech)
        db.session.flush()

        # Legacy-style row with no SMART INSIGHTS recommendations section.
        db.session.add(
            Activity(
                activity_type="rca",
                details="Site Number: LEG-001\nSite Name: Legacy Site\nIssue: Old imported record",
                created_by=tech.email,
                risk_score=92,
                sla_deadline=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
                approved_at=None,
            )
        )
        db.session.add(
            Activity(
                activity_type="pm",
                details="Site Number: LEG-002\nSite Name: Legacy Site 2\nIssue: Pending checks",
                created_by=tech.email,
                risk_score=45,
                sla_deadline=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2),
                approved_at=None,
            )
        )
        db.session.add(
            Activity(
                activity_type="pm",
                details="Site Number: LEG-003\nSite Name: Legacy Site 3\nIssue: Stable pending closure",
                created_by=tech.email,
                risk_score=30,
                sla_deadline=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=18),
                approved_at=None,
            )
        )
        db.session.commit()

    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    response = client.get("/desk/activities/", follow_redirects=False)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "SLA breached: escalate immediately" in body
    assert "SLA due soon" in body
    assert "SLA is on track" in body


def test_live_dashboard_counts_api_returns_counts_and_notifications(app, client, staff_user):
    with app.app_context():
        db.session.add(
            User(
                email="live-tech@example.com",
                full_name="Live Tech",
                role="technician",
                password_hash=generate_password_hash("Password123!"),
            )
        )
        db.session.add(
            Activity(
                activity_type="pm",
                details="Site Number: LIVE-001\nSite Name: Live Site",
                created_by="live-tech@example.com",
                risk_score=75,
            )
        )
        db.session.add(
            Message(
                sender_email="live-tech@example.com",
                sender_role="technician",
                recipient_role="staff",
                body="New live form waiting.",
            )
        )
        db.session.commit()

    _login_user(client, staff_user["email"], staff_user["password"], role="staff")
    response = client.get("/api/live-dashboard-counts")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["counts"]["pending_pm_rcas"] >= 1
    assert payload["counts"]["high_risk_pending_pm_rcas"] >= 1
    assert payload["notification_count"] >= 1
    assert payload["latest_message_id"] is not None


def test_photo_quality_analysis_flags_low_resolution(writable_temp_dir):
    from app import analyze_uploaded_photo_quality

    image_path = writable_temp_dir / "tiny.png"
    image_path.write_bytes(_png_bytes(width=100, height=100))

    result = analyze_uploaded_photo_quality(str(image_path))

    assert result["width"] == 100
    assert result["height"] == 100
    assert result["warnings"]
    assert "resolution" in result["warnings"][0].lower()
