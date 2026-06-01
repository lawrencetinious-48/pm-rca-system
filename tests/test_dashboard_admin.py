import re

from tests.conftest import extract_hidden_input


def _login_as_admin(client, admin_user):
    response = client.get("/login?role=admin")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login?role=admin",
        data={
            "email": admin_user["email"],
            "password": admin_user["password"],
            "account_type": "admin",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]


def _login_as_developer(client, developer_user):
    response = client.get("/login?role=developer")
    assert response.status_code == 200
    token = extract_hidden_input(response.get_data(as_text=True), "login_csrf_token")

    response = client.post(
        "/login?role=developer",
        data={
            "email": developer_user["email"],
            "password": developer_user["password"],
            "account_type": "developer",
            "login_csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/dashboard/" in response.headers["Location"]


def test_admin_dashboard_renders_photo_library_count(client, admin_user):
    _login_as_admin(client, admin_user)

    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    match = re.search(
        r'href="/admin/photo-library".*?<h1 class="display-5 fw-bold">([^<]*)</h1>',
        html,
        re.S,
    )

    assert match is not None
    assert match.group(1).strip().isdigit()


def test_login_page_uses_admin_label(client):
    response = client.get("/login")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'href="/admin/login"' in html
    assert "Developer</a>" not in html


def test_admin_dashboard_uses_admin_urls_and_role_class(client, admin_user):
    _login_as_admin(client, admin_user)

    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'role-developer' not in html
    assert 'class="role-admin"' in html
    assert '/developer/users/block/' not in html
    assert '/developer/photo-library' not in html
    assert '/admin/users/block/' in html
    assert '/admin/photo-library' in html


def test_admin_dashboard_renders_share_link_card_and_qr(client, admin_user):
    _login_as_admin(client, admin_user)

    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'Shareable Technician Login Link + QR' in html
    assert 'id="loginShareUrl"' in html
    assert 'id="shareQrImage"' in html
    assert '/admin/share-qr.png' in html
    assert '/system/share-url' in html


def test_developer_dashboard_uses_admin_urls_and_role_class(client, developer_user):
    _login_as_developer(client, developer_user)

    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert 'role-developer' not in html
    assert 'class="role-admin"' in html
    assert '/developer/users/block/' not in html
    assert '/developer/photo-library' not in html
    assert '/admin/users/block/' in html
    assert '/admin/photo-library' in html
