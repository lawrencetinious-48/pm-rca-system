import json
from pathlib import Path

from PIL import Image
from werkzeug.security import generate_password_hash

from conftest import extract_hidden_input
from model import Consumable, User, db


def login_user(client, email, password, role):
    response = client.get(f"/login?role={role}")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        f"/login?role={role}",
        data={
            "email": email,
            "password": password,
            "account_type": role,
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]
    return response


def create_user(app, email, role):
    with app.app_context():
        user = User(
            email=email,
            full_name=f"{role.title()} User",
            role=role,
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.commit()
        return user


def test_api_create_consumable_allows_staff(client, app):
    create_user(app, "dev-consumable@example.com", "developer")
    login_user(client, "dev-consumable@example.com", "Password123!", "developer")

    payload = {
        "site_id": "TEST-001",
        "site_name": "Test Site 1",
        "description": "Consumable request for inspection.",
        "location": "10.0000N 20.0000E",
        "signage_image_url": "https://example.com/uploads/test.png",
        "screenshot_url": "{}",
    }

    response = client.post("/api/consumables/", json=payload)
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["id"] is not None

    with app.app_context():
        item = db.session.get(Consumable, data["id"])
        assert item is not None
        assert item.created_by == "dev-consumable@example.com"
        assert item.site_name == "Test Site 1"


def test_api_create_consumable_denies_developer(client, app):
    create_user(app, "staff-consumable-deny@example.com", "staff")
    login_user(client, "staff-consumable-deny@example.com", "Password123!", "staff")

    response = client.post(
        "/api/consumables/",
        json={
            "site_id": "TEST-002",
            "site_name": "Staff Site",
            "description": "Staff should not create through API.",
        },
    )
    assert response.status_code == 403
    data = response.get_json()
    assert data["code"] == "FORBIDDEN"


def test_api_approve_consumable_allows_staff(client, app):
    create_user(app, "staff-approve@example.com", "staff")
    login_user(client, "staff-approve@example.com", "Password123!", "staff")

    with app.app_context():
        item = Consumable(
            site_id="TEST-003",
            site_name="Approvals Site",
            description="Pending approval.",
            created_by="creator@example.com",
            signage_image_url=None,
            screenshot_url="{}",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    response = client.post(
        f"/api/consumables/{item_id}/approve",
        json={"treatment_given": "Replaced filter", "review_notes": "Approved after inspection."},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"

    with app.app_context():
        item = db.session.get(Consumable, item_id)
        assert item.is_approved is True
        assert item.approved_by == "staff-approve@example.com"
        assert item.treatment_given == "Replaced filter"


def test_api_approve_consumable_denies_technician(client, app):
    create_user(app, "tech-approve@example.com", "technician")
    login_user(client, "tech-approve@example.com", "Password123!", "technician")

    with app.app_context():
        item = Consumable(
            site_id="TEST-004",
            site_name="Tech Denied Site",
            description="Should deny technician approval.",
            created_by="creator@example.com",
            signage_image_url=None,
            screenshot_url="{}",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    response = client.post(
        f"/api/consumables/{item_id}/approve",
        json={"treatment_given": "Attempted approval", "review_notes": "Technician cannot approve."},
    )
    assert response.status_code == 403
    data = response.get_json()
    assert data["code"] == "FORBIDDEN"


def test_consumable_pdf_route_returns_pdf_for_staff(client, app):
    create_user(app, "staff-pdf@example.com", "staff")
    login_user(client, "staff-pdf@example.com", "Password123!", "staff")

    with app.app_context():
        item = Consumable(
            site_id="TEST-005",
            site_name="PDF Site",
            description="PDF route test.",
            created_by="creator@example.com",
            signage_image_url="https://example.com/signage.png",
            screenshot_url='{"Front":"https://example.com/front.png"}',
            treatment_given="Replaced filter",
            review_notes="Review complete.",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    response = client.get(f"/consumables/{item_id}/pdf")
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    assert response.data.startswith(b"%PDF")

    pdf_text = response.data.decode("latin-1", errors="ignore")
    assert "Consumable Review Report" in pdf_text
    assert "Replaced filter" not in pdf_text
    assert "Treatment Given" not in pdf_text
    assert "Front" not in pdf_text


def test_consumables_page_shows_review_actions_for_desk_staff(client, app):
    create_user(app, "desk-staff-review@example.com", "desk_staff")
    login_user(client, "desk-staff-review@example.com", "Password123!", "desk_staff")

    with app.app_context():
        item = Consumable(
            site_id="TEST-005B",
            site_name="Desk Staff Review Site",
            description="Pending review for legacy desk staff role.",
            created_by="creator@example.com",
            screenshot_url="{}",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    response = client.get("/consumables/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'data-item-id="{item_id}"' in html
    assert 'consumable-approve-btn' in html
    assert 'consumable-reject-btn' in html


def test_consumable_detail_page_renders_before_and_after_images(client, app):
    create_user(app, "staff-detail@example.com", "staff")
    login_user(client, "staff-detail@example.com", "Password123!", "staff")

    with app.app_context():
        upload_dir = Path(client.application.config["UPLOAD_FOLDER"])
        upload_dir.mkdir(parents=True, exist_ok=True)
        before_path = upload_dir / "detail-before.jpg"
        after_path = upload_dir / "detail-after.jpg"
        Image.new("RGB", (1200, 900), color="white").save(before_path, format="JPEG")
        Image.new("RGB", (1200, 900), color="blue").save(after_path, format="JPEG")

        item = Consumable(
            site_id="TEST-006",
            site_name="Detail Site",
            description="Detail page image test.",
            created_by="creator@example.com",
            before_usage_image_url="/uploads/detail-before.jpg",
            screenshot_url=json.dumps({"after": "/uploads/detail-after.jpg"}),
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    response = client.get(f"/consumables/{item_id}/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Before Usage" in html
    assert "After Usage" in html
    assert "/uploads/detail-before.jpg" in html
    assert "/uploads/detail-after.jpg" in html


def test_consumable_pdf_includes_local_images_for_before_and_after(client, app):
    create_user(app, "staff-pdf-images@example.com", "staff")
    login_user(client, "staff-pdf-images@example.com", "Password123!", "staff")

    with app.app_context():
        upload_dir = Path(client.application.config["UPLOAD_FOLDER"])
        upload_dir.mkdir(parents=True, exist_ok=True)
        before_path = upload_dir / "pdf-before.jpg"
        after_path = upload_dir / "pdf-after.jpg"
        Image.new("RGB", (800, 600), color="white").save(before_path, format="JPEG")
        Image.new("RGB", (800, 600), color="green").save(after_path, format="JPEG")

        item = Consumable(
            site_id="TEST-007",
            site_name="Image PDF Site",
            description="PDF image inclusion test.",
            created_by="creator@example.com",
            before_usage_image_url="/uploads/pdf-before.jpg",
            screenshot_url=json.dumps({"after": "/uploads/pdf-after.jpg"}),
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    response = client.get(f"/consumables/{item_id}/pdf")
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    assert response.data.startswith(b"%PDF")
    assert b"/Subtype /Image" in response.data
