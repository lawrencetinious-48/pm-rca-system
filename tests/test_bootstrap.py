import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect

from model import BootstrapState, User, db
from pm_app.legacy_app import create_app


def test_create_app_bootstraps_missing_state(tmp_path):
    db_path = tmp_path / "bootstrap.sqlite"

    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "REDIS_URL": "redis://localhost:6379/0",
        }
    )

    with app.app_context():
        bootstrap_state = BootstrapState.query.first()
        assert bootstrap_state is not None
        assert os.path.isdir(app.config["UPLOAD_FOLDER"])
        assert os.path.isdir(app.config["PHOTO_LIBRARY_FOLDER"])


def test_create_app_creates_bootstrap_admin_from_env(tmp_path, monkeypatch):
    db_path = tmp_path / "bootstrap_admin.sqlite"
    monkeypatch.setenv("BOOTSTRAP_ADMIN_NAME", "Bootstrap Admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "bootstrap@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "StrongPass123!")

    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "REDIS_URL": "redis://localhost:6379/0",
        }
    )

    with app.app_context():
        admin = User.query.filter_by(email="bootstrap@example.com").first()
        bootstrap_state = BootstrapState.query.first()

        assert admin is not None
        assert admin.role == "admin"
        assert admin.full_name == "Bootstrap Admin"
        assert bootstrap_state is not None
        assert bootstrap_state.bootstrap_complete is True


def test_create_app_skips_bootstrap_during_migration(monkeypatch, tmp_path):
    db_path = tmp_path / "migration.sqlite"
    monkeypatch.setattr(sys, "argv", ["flask", "db", "upgrade"])

    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "REDIS_URL": "redis://localhost:6379/0",
        }
    )

    with app.app_context():
        inspector = inspect(db.engine)
        assert inspector.has_table("users") is False
        assert inspector.has_table("bootstrap_state") is False


def test_create_admin_marks_bootstrap_state_complete(tmp_path):
    db_path = tmp_path / "create_admin.sqlite"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{db_path}",
            "DEV_DATABASE_URL": f"sqlite:///{db_path}",
            "SECRET_KEY": "test-secret-key",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/create_admin.py",
            "--email",
            "admin@example.com",
            "--name",
            "Admin User",
            "--password",
            "StrongPass123!",
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    with sqlite3.connect(db_path) as conn:
        user_count = conn.execute("select count(*) from users").fetchone()[0]
        bootstrap_row = conn.execute(
            "select bootstrap_complete, first_developer_id from bootstrap_state"
        ).fetchone()

    assert user_count == 1
    assert bootstrap_row == (1, 1)


def test_create_admin_aborts_when_any_user_exists(tmp_path):
    db_path = tmp_path / "existing_user.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "REDIS_URL": "redis://localhost:6379/0",
        }
    )

    with app.app_context():
        db.session.add(
            User(
                email="existing@example.com",
                full_name="Existing User",
                password_hash="hash",
                role="staff",
            )
        )
        db.session.commit()

    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{db_path}",
            "DEV_DATABASE_URL": f"sqlite:///{db_path}",
            "SECRET_KEY": "test-secret-key",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/create_admin.py",
            "--email",
            "new@example.com",
            "--name",
            "New Admin",
            "--password",
            "StrongPass123!",
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1

    with sqlite3.connect(db_path) as conn:
        user_count = conn.execute("select count(*) from users").fetchone()[0]

    assert user_count == 1
