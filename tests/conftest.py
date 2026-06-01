import contextlib
import os
import re
import shutil
import uuid
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from model import Consumable, User, db
from pm_app.legacy_app import create_app


def extract_hidden_input(html: str, field_name: str) -> str:
    pattern = rf'name="{re.escape(field_name)}" value="([^"]+)"'
    match = re.search(pattern, html)
    if not match:
        raise AssertionError(f"Hidden field {field_name!r} was not found in response HTML")
    return match.group(1)


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / f"test_pm_{uuid.uuid4().hex}.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SEED_SAMPLE_DATA": False,
            "WTF_CSRF_ENABLED": False,
            "PASSWORD_HASH_METHOD": "pbkdf2:sha256:1",
        }
    )

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

    yield app

    try:
        with app.app_context():
            db.session.remove()
            db.drop_all()
    except Exception:
        pass
    with contextlib.suppress(OSError):
        database_path.unlink()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def writable_temp_dir(tmp_path):
    temp_dir = tmp_path / f"test_tmp_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    yield temp_dir


@pytest.fixture()
def developer_user(app):
    with app.app_context():
        user = User(
            email="developer@example.com",
            full_name="Developer User",
            role="developer",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.commit()
        return {"email": user.email, "password": "Password123!"}


@pytest.fixture()
def admin_user(app):
    with app.app_context():
        user = User(
            email="admin@example.com",
            full_name="Admin User",
            role="admin",
            password_hash=generate_password_hash("Password123!"),
        )
        db.session.add(user)
        db.session.commit()
        return {"email": user.email, "password": "Password123!"}


@pytest.fixture()
def login_as_developer(client, developer_user):
    def _login(*, base_url=None):
        request_kwargs = {}
        if base_url:
            request_kwargs["base_url"] = base_url

        response = client.get("/login?role=developer", **request_kwargs)
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
            **request_kwargs,
        )
        assert response.status_code == 302
        assert "/dashboard/" in response.headers["Location"]
        return response

    return _login


@pytest.fixture()
def consumable_count(app):
    with app.app_context():
        return Consumable.query.count()
