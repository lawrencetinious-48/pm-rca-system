from pathlib import Path

from model import BootstrapState, User, db
from pm_app.legacy_app import create_app


def test_local_sqlite_restarts_empty_when_reset_enabled(tmp_path):
    db_path = tmp_path / "dev_pm.sqlite"

    app = create_app(
        {
            "TESTING": False,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "RESET_DEV_DB_ON_START": True,
        }
    )

    with app.app_context():
        db.create_all()
        user = User(
            email="manager@example.com",
            full_name="Manager User",
            role="manager",
            password_hash="hashed-password",
        )
        db.session.add(user)
        db.session.commit()

    fresh_app = create_app(
        {
            "TESTING": False,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "RESET_DEV_DB_ON_START": True,
        }
    )

    with fresh_app.app_context():
        assert db.session.query(User).count() == 0
        assert db.session.query(BootstrapState).count() == 1
        bootstrap = db.session.query(BootstrapState).first()
        assert bootstrap.bootstrap_complete is False
