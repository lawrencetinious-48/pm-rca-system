import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash

from model import Activity, Consumable, User, db, UserSettings

from conftest import extract_hidden_input


def _login_as_staff(client):
    staff_email = "staff-consumables@example.com"
    staff_password = "Password123!"

    with client.application.app_context():
        user = User(
            email=staff_email,
            full_name="Staff Consumables User",
            role="staff",
            password_hash=generate_password_hash(staff_password),
        )
        db.session.add(user)
        db.session.commit()

    response = client.get("/login?role=staff")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login?role=staff",
        data={
            "email": staff_email,
            "password": staff_password,
            "account_type": "staff",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]
    return response


def test_dashboard_redirects_anonymous_user(client):
    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_response_echoes_request_id_header(client):
    response = client.get("/login", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-123"


def test_login_page_lists_all_supported_account_types(client):
    response = client.get("/login")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'value="developer"' in body
    assert 'value="staff"' in body
    assert 'value="manager"' in body
    assert 'value="general_manager"' in body
    assert 'value="technician"' in body


def test_login_page_exposes_dropdown_pill_account_selector(client):
    response = client.get("/login")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'id="accountType"' in body
    assert 'name="account_type"' in body
    assert 'id="rolePillDropdownToggle"' in body
    assert 'id="rolePillDropdown"' in body
    assert 'id="rolePillRow"' in body


def test_login_page_uses_login_shell_override(client):
    response = client.get("/login")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    css_text = Path("static/style.css").read_text(encoding="utf-8", errors="ignore")

    assert "login-shell" in body
    assert "body.login-shell" in css_text
    assert "background-watermark.jpeg" not in body


def test_login_page_hides_first_time_setup_after_user_exists(client, developer_user):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Create the first admin account" not in response.get_data(as_text=True)


def test_self_service_create_developer_is_hidden_after_first_user(app, client, developer_user):
    with app.app_context():
        app.config["SELF_SERVICE_ENABLED"] = True

    response = client.get("/admin/self-service/create-developer")
    assert response.status_code == 404


def test_role_locked_login_page_preserves_hidden_account_type(client):
    response = client.get("/login?role=developer")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '<input type="hidden" name="account_type" value="developer">' in body


def test_first_user_registration_page_is_public(client):
    response = client.get("/register/")
    assert response.status_code == 200
    assert "Create Admin Account" in response.get_data(as_text=True)


def test_registration_locks_after_first_user_exists(client, developer_user):
    response = client.get("/register/")
    assert response.status_code == 403


def test_developer_login_redirects_to_dashboard(login_as_developer):
    response = login_as_developer()
    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]


def test_logout_post_to_root_path_logs_out_user(login_as_developer, client):
    login_as_developer()

    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logout_post_to_trailing_slash_path_logs_out_user(login_as_developer, client):
    login_as_developer()

    response = client.post("/logout/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_uses_account_type_field_for_authentication(app, client):
    with app.app_context():
        user = User(
            email="staff-login@example.com",
            full_name="Staff Login",
            role="staff",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.commit()

    response = client.get("/login")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login",
        data={
            "email": "staff-login@example.com",
            "password": "Password123!",
            "account_type": "staff",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]


def test_login_accepts_legacy_desk_staff_account_type(app, client):
    with app.app_context():
        user = User(
            email="deskstaff-login@example.com",
            full_name="Desk Staff Login",
            role="desk_staff",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.commit()

    response = client.get("/login")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login",
        data={
            "email": "deskstaff-login@example.com",
            "password": "Password123!",
            "account_type": "desk_staff",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]


def test_api_create_consumable_uses_authenticated_identity(app, client, developer_user, login_as_developer):
    login_as_developer()

    response = client.post(
        "/api/consumables/",
        json={
            "site_id": "SITE-001",
            "site_name": "Alpha Site",
            "description": "Smoke test consumable creation",
            "created_by": "spoofed@example.com",
        },
    )

    assert response.status_code == 201

    with app.app_context():
        record = db.session.get(Consumable, response.get_json()["id"])
        assert record is not None
        assert record.created_by == developer_user["email"]


def test_user_settings_persist_in_database(app, client, developer_user, login_as_developer):
    """Test that user settings (theme, language) are saved and loaded from database."""
    # Login as developer
    login_as_developer()

    # Get the developer user from database
    from model import User
    with app.app_context():
        user = db.session.query(User).filter_by(email=developer_user["email"]).first()
        assert user is not None

        # Initially no settings should exist
        initial_settings = db.session.query(UserSettings).filter_by(user_id=user.id).first()
        assert initial_settings is None

    # Fetch settings page first to get CSRF token for POST.
    response = client.get("/settings/")
    assert response.status_code == 200
    csrf_token = extract_hidden_input(response.get_data(as_text=True), "csrf_token")

    # POST to settings endpoint to save theme and language
    response = client.post(
        "/settings/",
        data={
            "theme": "dark",
            "language": "sw",
            "save_section": "sla_policy",
            "sla_enabled": "active",
            "sla_standard_hours": "36",
            "sla_critical_hours": "18",
            "sla_due_soon_hours": "4",
            "sla_policy_agreed": "on",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302  # redirect on success

    # Verify settings were saved to database
    with app.app_context():
        user_settings = db.session.query(UserSettings).filter_by(user_id=user.id).first()
        assert user_settings is not None
        assert user_settings.theme == "dark"
        assert user_settings.language == "sw"
        preferences = user_settings.get_preferences()
        assert preferences["sla_policy"]["enabled"] is True
        assert preferences["sla_policy"]["standard_hours"] == 36
        assert preferences["sla_policy"]["critical_hours"] == 18
        assert preferences["sla_policy"]["due_soon_hours"] == 4

        active_policy = app.config["_get_active_sla_policy"]()
        assert active_policy["standard_hours"] == 36
        assert active_policy["critical_hours"] == 18
        assert active_policy["due_soon_hours"] == 4

    # GET settings page should reflect saved settings in session.
    response = client.get("/settings/")
    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("theme") == "dark"
        assert sess.get("language") == "sw"


def test_consumables_page_uses_pagination(app, client, developer_user):
    _login_as_staff(client)

    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for index in range(60):
            db.session.add(
                Consumable(
                    site_id=f"SITE-{index:03d}",
                    site_name=f"Site {index}",
                    description="Pagination test",
                    created_by=developer_user["email"],
                    created_at=now + timedelta(seconds=index),
                )
            )
        db.session.commit()

    response = client.get("/api/consumables/?per_page=25")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["total"] == 60
    assert body["per_page"] == 25
    assert len(body.get("items", [])) == 25


def test_consumables_page_default_pagination_is_five(app, client, developer_user):
    _login_as_staff(client)

    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for index in range(7):
            db.session.add(
                Consumable(
                    site_id=f"PAG-{index:02d}",
                    site_name=f"Pag Site {index}",
                    description="Pagination test",
                    created_by=developer_user["email"],
                    created_at=now + timedelta(seconds=index),
                )
            )
        db.session.commit()

    response = client.get("/consumables/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Showing 5 of 7 consumables on page 1 of 2.' in html


def test_consumables_show_retake_controls_for_photo_uploads(client):
    _login_as_staff(client)

    response = client.get("/consumables/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Delete & retake" in html
    assert 'capture="environment"' in html


def test_consumables_page_renders_share_qr_controls(client):
    response = client.get("/system/share-url")
    assert response.status_code == 302

    _login_as_staff(client)
    response = client.get("/system/share-url")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="shareQrImage"' in html
    assert 'id="shareQrStatus"' in html
    assert 'id="refreshQrBtn"' in html


def test_consumables_uploads_are_resized_and_preserve_aspect_ratio(client):
    _login_as_staff(client)

    before_buffer = BytesIO()
    Image.new("RGB", (2400, 1800), color="white").save(before_buffer, format="JPEG")
    before_buffer.seek(0)

    after_buffer = BytesIO()
    Image.new("RGB", (2400, 1800), color="lightgray").save(after_buffer, format="JPEG")
    after_buffer.seek(0)

    response = client.post(
        "/consumables/",
        data={
            "site_id": "SITE-001",
            "site_name": "Main Site",
            "description": "Need a replacement consumable.",
            "location": "District 4",
            "before_usage_label": "Before usage",
            "before_usage_image": (before_buffer, "before.jpg"),
            "after_usage_label": "After usage",
            "after_usage_image": (after_buffer, "after.jpg"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with client.application.app_context():
        item = Consumable.query.order_by(Consumable.created_at.desc()).first()
        assert item is not None
        assert item.before_usage_image_url
        assert json.loads(item.screenshot_url)["after"]
        before_name = item.before_usage_image_url.rsplit("/", 1)[-1]
        after_name = json.loads(item.screenshot_url)["after"].rsplit("/", 1)[-1]
        before_path = Path(client.application.config["UPLOAD_FOLDER"]) / before_name
        after_path = Path(client.application.config["UPLOAD_FOLDER"]) / after_name
        assert before_path.exists()
        assert after_path.exists()

        with Image.open(before_path) as saved_image:
            assert saved_image.width <= 1600
            assert saved_image.height <= 1600
            assert saved_image.width < 2400
            assert saved_image.height < 1800

        with Image.open(after_path) as saved_image:
            assert saved_image.width <= 1600
            assert saved_image.height <= 1600
            assert saved_image.width < 2400
            assert saved_image.height < 1800


def test_non_admin_users_cannot_change_password_via_settings(client):
    _login_as_staff(client)

    response = client.get("/settings/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Password changes are handled by an administrator." in html
    assert 'name="current_password"' not in html

    response = client.post(
        "/settings/",
        data={
            "save_section": "change_password",
            "current_password": "Password123!",
            "new_password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Password updates are managed by an administrator." in body

    with client.application.app_context():
        user = User.query.filter_by(email="staff-consumables@example.com").first()
        assert user is not None
        assert check_password_hash(user.password_hash, "Password123!")


def test_admin_staff_page_uses_pagination(app, client, developer_user, login_as_developer):
    login_as_developer()

    with app.app_context():
        for index in range(30):
            db.session.add(
                User(
                    email=f"staff-{index}@example.com",
                    full_name=f"Staff {index}",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                )
            )
        db.session.commit()

    response = client.get("/admin/staff/?per_page=10")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Showing 10 of 31 matched users on page 1 of 4." in body
    assert "Edit Profile" in body


def test_delete_user_with_settings_succeeds(app, client, login_as_developer):
    login_as_developer()

    with app.app_context():
        target = User(
            email="delete-settings@example.com",
            full_name="Delete Settings",
            role="staff",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(target)
        db.session.commit()

        target_settings = UserSettings(user_id=target.id, theme="dark", language="sw")
        db.session.add(target_settings)
        db.session.commit()
        target_id = target.id

    response = client.get("/admin/staff/")
    assert response.status_code == 200
    csrf_token = extract_hidden_input(response.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/admin/staff/{target_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(User, target_id) is None
        assert UserSettings.query.filter_by(user_id=target_id).first() is None


def test_run_maintenance_command_escalates_overdue_high_risk_item(app):
    with app.app_context():
        tech = User(
            email="cli-tech@example.com",
            full_name="CLI Tech",
            role="technician",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(tech)
        db.session.add(
            Activity(
                activity_type="pm",
                details="CLI maintenance escalation test",
                created_by=tech.email,
                risk_score=95,
                sla_deadline=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
                approved_at=None,
            )
        )
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["run-maintenance"])

    assert result.exit_code == 0
    assert "sla_escalations=1" in result.output


def test_developer_dashboard_shareable_link_targets_technician_login(client, login_as_developer):
    login_as_developer()

    response = client.get("/dashboard/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/technician/login" in body


def test_developer_can_create_staff_without_manual_password(app, client, login_as_developer):
    login_as_developer()

    response = client.get("/admin/add-staff/")
    assert response.status_code == 200
    csrf_token = extract_hidden_input(response.get_data(as_text=True), "csrf_token")

    response = client.post(
        "/admin/add-staff/",
        data={
            "csrf_token": csrf_token,
            "first_name": "Auto",
            "last_name": "Password",
            "email": "auto-password@example.com",
            "region": "Central",
            "gender": "male",
            "password": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Staff account created" in body
    assert "Latest Issued Credentials" in body
    assert "Auto-generated by system" in body


def test_reset_password_shows_current_and_new_password_in_issued_credentials(app, client, login_as_developer):
    login_as_developer()

    with app.app_context():
        target = User(
            email="reset-target@example.com",
            full_name="Reset Target",
            role="staff",
            password_hash=generate_password_hash("OldPass123!"),
        )
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    response = client.get("/admin/staff/")
    assert response.status_code == 200
    csrf_token = extract_hidden_input(response.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/admin/staff/{target_id}/reset-password",
        data={
            "csrf_token": csrf_token,
            "current_password": "OldPass123!",
            "new_password": "NewPass456!",
            "q": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Password reset for Reset Target." in body
    assert "Previous Password (Provided):" in body
    assert "OldPass123!" in body


def test_generate_temporary_password_on_reset_when_blank(app, client, login_as_developer):
    login_as_developer()

    with app.app_context():
        target = User(
            email="generate-temp-target@example.com",
            full_name="Generate Temp Target",
            role="staff",
            password_hash=generate_password_hash("OldPass123!"),
        )
        db.session.add(target)
        db.session.commit()
        target_id = target.id

    response = client.get("/admin/staff/")
    assert response.status_code == 200
    csrf_token = extract_hidden_input(response.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/admin/staff/{target_id}/reset-password",
        data={
            "csrf_token": csrf_token,
            "new_password": "",
            "generate_only": "1",
            "q": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Password reset for Generate Temp Target." in body
    assert "Password:" in body
    assert "Previous Password (Provided):" not in body


def test_login_rejects_valid_credentials_with_wrong_account_type(app, client):
    with app.app_context():
        user = User(
            email="technician-login@example.com",
            full_name="Technician Login",
            role="technician",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.commit()

    response = client.get("/login")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login",
        data={
            "email": "technician-login@example.com",
            "password": "Password123!",
            "account_type": "manager",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "Invalid credentials." in response.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_activity_approve_reject_get_routes_redirect_instead_of_405(app, client):
    with app.app_context():
        staff = User(
            email="desk-staff@example.com",
            full_name="Desk Staff",
            role="staff",
            password_hash=generate_password_hash("Password123!"),
        )
        activity = Activity(
            activity_type="pm",
            details="Desk route fallback check",
            created_by="desk-staff@example.com",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.session.add(staff)
        db.session.add(activity)
        db.session.commit()
        activity_id = activity.id

    response = client.get("/login")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")
    login_response = client.post(
        "/login",
        data={
            "email": "desk-staff@example.com",
            "password": "Password123!",
            "account_type": "staff",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    approve_response = client.get(f"/activity/{activity_id}/approve", follow_redirects=False)
    reject_response = client.get(f"/activity/{activity_id}/reject", follow_redirects=False)

    assert approve_response.status_code == 302
    assert reject_response.status_code == 302


def test_developer_security_posture_endpoint_requires_developer_role(app, client):
    with app.app_context():
        staff = User(
            email="posture-staff@example.com",
            full_name="Posture Staff",
            role="staff",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(staff)
        db.session.commit()

    response = client.get("/login")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")
    login_response = client.post(
        "/login",
        data={
            "email": "posture-staff@example.com",
            "password": "Password123!",
            "account_type": "staff",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 302

    denied = client.get("/developer/security-posture")
    assert denied.status_code == 403


def test_developer_security_posture_endpoint_returns_runtime_config(client, login_as_developer):
    login_as_developer()
    response = client.get("/developer/security-posture")
    assert response.status_code == 200

    payload = response.get_json()
    assert isinstance(payload, dict)
    assert "session_cookie_secure" in payload
    assert "remember_cookie_secure" in payload
    assert "preferred_url_scheme" in payload
    assert "csrf_on" in payload
    assert "session_httponly" in payload
    assert "same_site_policy" in payload
    assert "checked_at" in payload
