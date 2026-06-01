from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

from conftest import extract_hidden_input
from model import Activity, FormAssignment, Message, User, UserSettings, db
from pm_app.legacy_helpers import _HOLIDAYS_CONFIG, get_public_holidays


def test_current_year_has_holiday_configuration():
    """Test that the current year has holiday configuration defined."""
    current_year = datetime.now(timezone.utc).year
    assert current_year in _HOLIDAYS_CONFIG, f"No holidays configured for year {current_year}"
    assert len(_HOLIDAYS_CONFIG[current_year]) > 0, f"Empty holiday list for year {current_year}"


def test_get_public_holidays_returns_current_year():
    """Test that get_public_holidays returns holidays for the current year."""
    current_year = datetime.now(timezone.utc).year
    holidays = get_public_holidays()
    assert holidays == _HOLIDAYS_CONFIG[current_year]


def login_user(client, email, password, role):
    response = client.get("/login")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login",
        data={
            "email": email,
            "password": password,
            "account_type": role,
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_send_message_persists_and_logs_activity(app, client):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="technician@example.com",
                    full_name="Tech User",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="staff@example.com",
                    full_name="Staff User",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.commit()

    login_user(client, "technician@example.com", "Password123!", "technician")

    response = client.get("/notifications/")
    assert response.status_code == 200
    csrf_token = extract_hidden_input(response.get_data(as_text=True), "csrf_token")

    response = client.post(
        "/notifications/messages/send",
        data={
            "csrf_token": csrf_token,
            "recipient_role": "staff",
            "message_body": "Need desk support on this PM ticket.",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Message sent successfully." in html

    with app.app_context():
        message = Message.query.one()
        assert message.sender_email == "technician@example.com"
        assert message.sender_role == "technician"
        assert message.recipient_role == "staff"
        assert message.body == "Need desk support on this PM ticket."

        activity = Activity.query.filter_by(activity_type="message").one()
        assert activity.created_by == "technician@example.com"
        assert "sent a message to staff" in activity.details


def test_notifications_inbox_uses_normalized_role_matching(app):
    with app.app_context():
        user = User(
            email="deskstaff@example.com",
            full_name="Desk Staff",
            role="desk_staff",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            Message(
                sender_email="technician@example.com",
                sender_role="technician",
                recipient_role="staff",
                recipient_email=None,
                body="Normalized role delivery test",
            )
        )
        db.session.commit()

    client = app.test_client()
    login_user(client, "deskstaff@example.com", "Password123!", "staff")

    response = client.get("/notifications/")
    assert response.status_code == 200
    assert "Normalized role delivery test" in response.get_data(as_text=True)


def test_send_message_get_redirects_to_notifications(login_as_developer, client):
    login_as_developer()

    response = client.get("/notifications/messages/send", follow_redirects=False)

    assert response.status_code == 302
    assert "/notifications/" in response.headers["Location"]


def test_sender_sees_delete_button_on_notifications_list(app):
    with app.app_context():
        db.session.add(
            User(
                email="visible-owner@example.com",
                full_name="Visible Owner",
                role="staff",
                password_hash=generate_password_hash("Password123!"),
            )
        )
        db.session.add(
            Message(
                sender_email="visible-owner@example.com",
                sender_role="staff",
                recipient_role="staff",
                recipient_email=None,
                body="show-delete-button",
            )
        )
        db.session.commit()

    client = app.test_client()
    login_user(client, "visible-owner@example.com", "Password123!", "staff")

    response = client.get("/notifications/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Delete Message" in body


def test_relevant_non_sender_sees_delete_button_on_notifications_list(app):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="sender-two@example.com",
                    full_name="Sender Two",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="receiver-two@example.com",
                    full_name="Receiver Two",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        db.session.add(
            Message(
                sender_email="sender-two@example.com",
                sender_role="technician",
                recipient_role="staff",
                recipient_email=None,
                body="has-delete-button",
            )
        )
        db.session.commit()

    client = app.test_client()
    login_user(client, "receiver-two@example.com", "Password123!", "staff")

    response = client.get("/notifications/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Delete Message" in body


def test_sender_can_delete_own_message(app):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="owner@example.com",
                    full_name="Owner User",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="recipient@example.com",
                    full_name="Recipient User",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        msg = Message(
            sender_email="owner@example.com",
            sender_role="staff",
            recipient_role="staff",
            recipient_email=None,
            body="delete-me",
        )
        db.session.add(msg)
        db.session.commit()
        message_id = msg.id

    client = app.test_client()
    login_user(client, "owner@example.com", "Password123!", "staff")

    page = client.get("/notifications/")
    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/notifications/messages/{message_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Message hidden from your inbox." in response.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(Message, message_id) is not None
        settings = UserSettings.query.filter_by(user_id=User.query.filter_by(email="owner@example.com").first().id).first()
        assert settings is not None
        hidden_ids = settings.get_preferences().get("hidden_message_ids", [])
        assert message_id in hidden_ids


def test_non_sender_cannot_delete_message(app):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="sender@example.com",
                    full_name="Sender User",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="other@example.com",
                    full_name="Other User",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        msg = Message(
            sender_email="sender@example.com",
            sender_role="technician",
            recipient_role="staff",
            recipient_email=None,
            body="should-stay",
        )
        db.session.add(msg)
        db.session.commit()
        message_id = msg.id

    client = app.test_client()
    login_user(client, "other@example.com", "Password123!", "staff")

    page = client.get("/notifications/")
    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/notifications/messages/{message_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Message hidden from your inbox." in response.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(Message, message_id) is not None
        settings = UserSettings.query.filter_by(user_id=User.query.filter_by(email="other@example.com").first().id).first()
        assert settings is not None
        hidden_ids = settings.get_preferences().get("hidden_message_ids", [])
        assert message_id in hidden_ids


def test_developer_can_permanently_delete_other_users_message(app):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="developer-owner@example.com",
                    full_name="Developer User",
                    role="developer",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="sender-three@example.com",
                    full_name="Sender Three",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        msg = Message(
            sender_email="sender-three@example.com",
            sender_role="staff",
            recipient_role="all",
            recipient_email=None,
            body="developer-delete",
        )
        db.session.add(msg)
        db.session.commit()
        message_id = msg.id

    client = app.test_client()
    login_user(client, "developer-owner@example.com", "Password123!", "developer")

    page = client.get("/notifications/")
    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/notifications/messages/{message_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Message deleted." in response.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(Message, message_id) is None


def test_admin_can_permanently_delete_other_users_message(app):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="admin-owner@example.com",
                    full_name="Admin User",
                    role="admin",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="sender-admin@example.com",
                    full_name="Sender Admin",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        msg = Message(
            sender_email="sender-admin@example.com",
            sender_role="staff",
            recipient_role="all",
            recipient_email=None,
            body="admin-delete",
        )
        db.session.add(msg)
        db.session.commit()
        message_id = msg.id

    client = app.test_client()
    login_user(client, "admin-owner@example.com", "Password123!", "admin")

    page = client.get("/notifications/")
    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/notifications/messages/{message_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Message deleted." in response.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(Message, message_id) is None


def test_manager_can_hide_message_from_notifications_inbox(app):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="manager-user@example.com",
                    full_name="Manager User",
                    role="manager",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="sender-four@example.com",
                    full_name="Sender Four",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        msg = Message(
            sender_email="sender-four@example.com",
            sender_role="staff",
            recipient_role="manager",
            recipient_email=None,
            body="manager-hide-message",
        )
        db.session.add(msg)
        db.session.commit()
        message_id = msg.id

    client = app.test_client()
    login_user(client, "manager-user@example.com", "Password123!", "manager")

    page = client.get("/notifications/")
    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/notifications/messages/{message_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Message hidden from your inbox." in response.get_data(as_text=True)

    with app.app_context():
        assert db.session.get(Message, message_id) is not None
        settings = UserSettings.query.filter_by(user_id=User.query.filter_by(email="manager-user@example.com").first().id).first()
        assert settings is not None
        hidden_ids = settings.get_preferences().get("hidden_message_ids", [])
        assert message_id in hidden_ids


def test_staff_can_escalate_form_to_manager(app, client):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="tech-submit@example.com",
                    full_name="Tech Submit",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="staff-review@example.com",
                    full_name="Staff Review",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="manager-review@example.com",
                    full_name="Manager Review",
                    role="manager",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        activity = Activity(
            activity_type="pm",
            details="Test PM form details",
            created_by="tech-submit@example.com",
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(activity)
        db.session.commit()
        activity_id = activity.id

    client = app.test_client()
    login_user(client, "staff-review@example.com", "Password123!", "staff")

    page = client.get(f"/activity/{activity_id}/view")
    assert page.status_code == 200
    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/activity/{activity_id}/escalate",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Form escalated to managers for review." in response.get_data(as_text=True)

    with app.app_context():
        assignment = FormAssignment.query.filter_by(activity_id=activity_id, assignee_role="manager").one_or_none()
        assert assignment is not None
        assert assignment.status == "pending"
        staff_assignments = FormAssignment.query.filter_by(activity_id=activity_id, assignee_role="staff").all()
        assert all(a.status == "escalated" for a in staff_assignments)
        message = Message.query.filter_by(recipient_role="manager", sender_email="staff-review@example.com").one_or_none()
        assert message is not None
        assert "escalated to managers" in message.body


def test_manager_cannot_approve_without_toggle(app, client):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="manager-test@example.com",
                    full_name="Manager Test",
                    role="manager",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="tech-submit2@example.com",
                    full_name="Tech Submit 2",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        activity = Activity(
            activity_type="pm",
            details="Test PM form details",
            created_by="tech-submit2@example.com",
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(activity)
        db.session.commit()
        activity_id = activity.id

    client = app.test_client()
    login_user(client, "manager-test@example.com", "Password123!", "manager")

    page = client.get(f"/activity/{activity_id}/view")
    assert page.status_code == 200
    assert "Approve" not in page.get_data(as_text=True)
    assert "Reject" not in page.get_data(as_text=True)


def test_manager_can_approve_when_toggle_enabled(app, client):
    with app.app_context():
        app.config["MANAGER_CAN_APPROVE"] = True
        db.session.add_all(
            [
                User(
                    email="manager-enabled@example.com",
                    full_name="Manager Enabled",
                    role="manager",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="tech-submit3@example.com",
                    full_name="Tech Submit 3",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        activity = Activity(
            activity_type="pm",
            details="Test PM form details",
            created_by="tech-submit3@example.com",
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(activity)
        db.session.commit()
        activity_id = activity.id

    client = app.test_client()
    login_user(client, "manager-enabled@example.com", "Password123!", "manager")

    page = client.get(f"/activity/{activity_id}/view")
    assert page.status_code == 200
    assert "Approve" not in page.get_data(as_text=True)
    assert "Reject" not in page.get_data(as_text=True)

    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")
    response = client.post(
        f"/activity/{activity_id}/approve",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "You are not authorised to approve this form." in response.get_data(as_text=True)

    with app.app_context():
        activity = db.session.get(Activity, activity_id)
        assert activity.is_approved is False
        assert activity.approved_by is None


def test_manager_can_approve_only_when_assigned(app, client):
    with app.app_context():
        app.config["MANAGER_CAN_APPROVE"] = True
        db.session.add_all(
            [
                User(
                    email="assigned-manager@example.com",
                    full_name="Assigned Manager",
                    role="manager",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="tech-submit4@example.com",
                    full_name="Tech Submit 4",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.flush()
        activity = Activity(
            activity_type="rca",
            details="Assigned manager review test",
            created_by="tech-submit4@example.com",
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(activity)
        db.session.flush()
        db.session.add(
            FormAssignment(
                activity_id=activity.id,
                assignee_email="assigned-manager@example.com",
                assignee_role="manager",
                status="pending",
            )
        )
        db.session.commit()
        activity_id = activity.id

    client = app.test_client()
    login_user(client, "assigned-manager@example.com", "Password123!", "manager")

    page = client.get(f"/activity/{activity_id}/view")
    assert page.status_code == 200
    assert "Approve" in page.get_data(as_text=True)
    assert "Reject" in page.get_data(as_text=True)

    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")
    response = client.post(
        f"/activity/{activity_id}/approve",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Activity approved" in response.get_data(as_text=True)

    with app.app_context():
        activity = db.session.get(Activity, activity_id)
        assert activity.is_approved is True
        assert activity.approved_by == "assigned-manager@example.com"

        assignment = FormAssignment.query.filter_by(activity_id=activity_id, assignee_email="assigned-manager@example.com").one()
        assert assignment.status == "approved"

    with app.app_context():
        owner = User(
            email="owner-bad-prefs@example.com",
            full_name="Owner Bad Prefs",
            role="staff",
            password_hash=generate_password_hash("Password123!"),
        )
        recipient = User(
            email="recipient-bad-prefs@example.com",
            full_name="Recipient Bad Prefs",
            role="staff",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add_all([owner, recipient])
        db.session.flush()

        db.session.add(
            UserSettings(
                user_id=owner.id,
                theme="light",
                language="en",
                preferences_json="[]",
            )
        )
        msg = Message(
            sender_email="owner-bad-prefs@example.com",
            sender_role="staff",
            recipient_role="staff",
            recipient_email=None,
            body="delete-bad-prefs",
        )
        db.session.add(msg)
        db.session.commit()
        message_id = msg.id

    client = app.test_client()
    login_user(client, "owner-bad-prefs@example.com", "Password123!", "staff")

    page = client.get("/notifications/")
    csrf_token = extract_hidden_input(page.get_data(as_text=True), "csrf_token")

    response = client.post(
        f"/notifications/messages/{message_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Message hidden from your inbox." in response.get_data(as_text=True)

    with app.app_context():
        settings = UserSettings.query.filter_by(user_id=User.query.filter_by(email="owner-bad-prefs@example.com").first().id).first()
        hidden_ids = settings.get_preferences().get("hidden_message_ids", [])
        assert message_id in hidden_ids
