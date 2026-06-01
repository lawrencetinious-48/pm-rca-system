import base64
import io
from datetime import datetime

from werkzeug.security import generate_password_hash

from conftest import extract_hidden_input
from model import Activity, Message, User, db


_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_SIGNATURE_DATA = "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode("ascii")


def _login(client, email, password, role):
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


def test_technician_submission_creates_staff_review_activity(app, client, writable_temp_dir):
    app.config["UPLOAD_FOLDER"] = str(writable_temp_dir)

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
            ]
        )
        db.session.commit()

    _login(client, "tech-submit@example.com", "Password123!", "technician")

    response = client.post(
        "/field/rca",
        data={
            "activity_type": "pm",
            "submitted_by": "Tech Submit",
            "activity_start": "2026-05-07",
            "activity_end": "2026-05-07",
            "validation_comments": "Routine maintenance complete.",
            "field_site_number": "UG-001",
            "field_site_name": "Kampala Central",
            "signature_data": _SIGNATURE_DATA,
            "photo_rectifier_settings_1": (io.BytesIO(_PNG_BYTES), "rectifier-1.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/field/report/" in response.headers["Location"]

    report_response = client.get(response.headers["Location"])
    assert report_response.status_code == 200
    report_html = report_response.get_data(as_text=True)
    assert "Form ID:" in report_html
    assert "PHOTO SPECIFICATIONS" in report_html
    assert "Tech Submit" in report_html

    with app.app_context():
        activity = Activity.query.filter_by(created_by="tech-submit@example.com", activity_type="pm").one()
        assert "Site Number: UG-001" in activity.details
        assert "Rectifier settings Photos_1" in activity.details
        assert activity.risk_score is not None
        assert activity.sla_deadline is not None

        message = Message.query.filter_by(recipient_role="staff").one()
        assert f"form #{activity.formatted_id}".lower() in message.body.lower()


def test_technician_submission_is_visible_on_staff_dashboard(app, client, writable_temp_dir):
    app.config["UPLOAD_FOLDER"] = str(writable_temp_dir)

    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="tech-visible-submit@example.com",
                    full_name="Tech Visible Submit",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="staff-dashboard-view@example.com",
                    full_name="Staff Dashboard View",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.commit()

    _login(client, "tech-visible-submit@example.com", "Password123!", "technician")

    response = client.post(
        "/field/rca",
        data={
            "activity_type": "rca",
            "submitted_by": "Tech Visible Submit",
            "activity_start": "2026-05-07",
            "activity_end": "2026-05-07",
            "validation_comments": "Issue identified and documented.",
            "field_site_number": "UG-002",
            "field_site_name": "Entebbe East",
            "signature_data": _SIGNATURE_DATA,
            "photo_rectifier_settings_1": (io.BytesIO(_PNG_BYTES), "rectifier-1.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/field/report/" in response.headers["Location"]

    _staff_login(client, "staff-dashboard-view@example.com", "Password123!")
    dashboard_response = client.get("/dashboard/")
    assert dashboard_response.status_code == 200
    dashboard_html = dashboard_response.get_data(as_text=True)
    assert "Latest Technician Submissions" in dashboard_html
    assert "tech-visible-submit@example.com" in dashboard_html


def test_technician_submission_appears_in_technician_submissions_list(app, client, writable_temp_dir):
    app.config["UPLOAD_FOLDER"] = str(writable_temp_dir)

    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="tech-list-submit@example.com",
                    full_name="Tech List Submit",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        db.session.commit()

    _login(client, "tech-list-submit@example.com", "Password123!", "technician")

    response = client.post(
        "/field/rca",
        data={
            "activity_type": "pm",
            "submitted_by": "Tech List Submit",
            "activity_start": "2026-05-07",
            "activity_end": "2026-05-07",
            "validation_comments": "Routine maintenance complete.",
            "field_site_number": "UG-003",
            "field_site_name": "Lakeside",
            "signature_data": _SIGNATURE_DATA,
            "photo_rectifier_settings_1": (io.BytesIO(_PNG_BYTES), "rectifier-1.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/field/report/" in response.headers["Location"]

    submissions_response = client.get("/field/submissions/")
    assert submissions_response.status_code == 200
    submissions_html = submissions_response.get_data(as_text=True)
    assert "My Submitted PM/RCA Forms" in submissions_html
    assert "#" in submissions_html
    assert "tech-list-submit@example.com" in submissions_html
    assert "PM" in submissions_html


def _staff_login(client, email, password):
    response = client.get("/login?role=staff")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login?role=staff",
        data={
            "email": email,
            "password": password,
            "account_type": "staff",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]
    return response


def test_desk_activities_forms_review_approved_with_month_filter(app, client):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="staff-receiver@example.com",
                    full_name="Staff Receiver",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="approved-tech@example.com",
                    full_name="Approved Tech",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        approved_activity = Activity(
            activity_type="pm",
            details="Site Number: ABC-123\nSite Name: Kampala Main",
            created_by="approved-tech@example.com",
            created_at=datetime(2026, 5, 7, 12, 0, 0),
            approved_at=datetime(2026, 5, 8, 13, 0, 0),
            is_approved=True,
        )
        rejected_activity = Activity(
            activity_type="rca",
            details="Site Number: XYZ-789\nSite Name: Entebbe East",
            created_by="rejected-tech@example.com",
            created_at=datetime(2026, 5, 8, 14, 0, 0),
            approved_at=datetime(2026, 5, 9, 15, 0, 0),
            is_approved=False,
        )
        pending_activity = Activity(
            activity_type="pm",
            details="Site Number: DEF-456\nSite Name: Jinja South",
            created_by="pending-tech@example.com",
            created_at=datetime(2026, 6, 1, 10, 0, 0),
        )
        db.session.add_all([approved_activity, rejected_activity, pending_activity])
        db.session.commit()

    _staff_login(client, "staff-receiver@example.com", "Password123!")
    response = client.get("/desk/activities/?mode=forms&review=approved&month=2026-05")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Total PM Forms" in body
    assert "Approved" in body
    assert "approved-tech@example.com" in body
    assert "rejected-tech@example.com" not in body
    assert "DEF-456" not in body
    assert 'value="2026-05"' in body


def test_desk_activities_forms_reviewed_pm_filter(app, client):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="staff-reviewer@example.com",
                    full_name="Staff Reviewer",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="approved-pm-tech@example.com",
                    full_name="Approved PM Tech",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
                User(
                    email="rejected-pm-tech@example.com",
                    full_name="Rejected PM Tech",
                    role="technician",
                    password_hash=generate_password_hash("Password123!"),
                ),
            ]
        )
        approved_pm = Activity(
            activity_type="pm",
            details="Site Number: PM-001\nSite Name: Main Plant",
            created_by="approved-pm-tech@example.com",
            created_at=datetime(2026, 5, 5, 9, 0, 0),
            approved_at=datetime(2026, 5, 6, 10, 0, 0),
            is_approved=True,
        )
        rejected_pm = Activity(
            activity_type="pm",
            details="Site Number: PM-002\nSite Name: Secondary Plant",
            created_by="rejected-pm-tech@example.com",
            created_at=datetime(2026, 5, 6, 11, 0, 0),
            approved_at=datetime(2026, 5, 7, 12, 0, 0),
            is_approved=False,
        )
        pending_rca = Activity(
            activity_type="rca",
            details="Site Number: RCA-001\nSite Name: Outpost",
            created_by="pending-rca-tech@example.com",
            created_at=datetime(2026, 5, 7, 13, 0, 0),
        )
        db.session.add_all([approved_pm, rejected_pm, pending_rca])
        db.session.commit()

    _staff_login(client, "staff-reviewer@example.com", "Password123!")
    response = client.get("/desk/activities/?mode=forms&review=reviewed&type=pm")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Reviewed PM Forms" in body
    assert "PM-001" in body
    assert "PM-002" in body
    assert "RCA-001" not in body
    assert "approved-pm-tech@example.com" in body
    assert "rejected-pm-tech@example.com" in body


def test_staff_dashboard_shows_latest_technician_submission(app, client):
    with app.app_context():
        db.session.add_all(
            [
                User(
                    email="staff-dashboard@example.com",
                    full_name="Staff Dashboard",
                    role="staff",
                    password_hash=generate_password_hash("Password123!"),
                ),
                Activity(
                    activity_type="rca",
                    details="PM FORM HEADER\nSite Number: UG-002\nSite Name: Entebbe",
                    created_by="tech-visible@example.com",
                ),
            ]
        )
        db.session.commit()

    _login(client, "staff-dashboard@example.com", "Password123!", "staff")
    response = client.get("/dashboard/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Latest Technician Submissions" in body
    assert "tech-visible@example.com" in body
