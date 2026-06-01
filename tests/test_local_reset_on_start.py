from pathlib import Path

from model import BootstrapState, User, db
from pm_app.legacy_app import create_app


def test_local_sqlite_reset_clears_existing_users_and_uploads(tmp_path):
    db_path = tmp_path / "dev_pm.sqlite"
    config = {
        "TESTING": False,
        "APP_ENV": "development",
        "SECRET_KEY": "test-secret-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "RESET_DEV_DB_ON_START": "1",
    }

    app = create_app(config)
    stale_upload = Path(app.config["UPLOAD_FOLDER"]) / "stale_upload.txt"
    stale_upload.parent.mkdir(exist_ok=True)
    stale_upload.write_text("stale", encoding="utf-8")

    try:
        with app.app_context():
            db.create_all()
            db.session.add(User(
                email="manager@example.com",
                full_name="Manager User",
                role="manager",
                password_hash="hash",
            ))
            db.session.add(BootstrapState(bootstrap_complete=True))
            db.session.commit()

        app = create_app(config)
        with app.app_context():
            assert db.session.query(User).count() == 0
            bootstrap_state = db.session.query(BootstrapState).first()
            assert bootstrap_state is not None
            assert bootstrap_state.bootstrap_complete is False
            assert not stale_upload.exists()
    finally:
        if stale_upload.exists():
            stale_upload.unlink()


def test_local_sqlite_keeps_existing_data_when_reset_flag_is_omitted(tmp_path):
    db_path = tmp_path / "dev_pm.sqlite"
    config = {
        "TESTING": False,
        "APP_ENV": "development",
        "SECRET_KEY": "test-secret-key",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
    }

    app = create_app(config)
    with app.app_context():
        db.create_all()
        db.session.add(User(
            email="preserved@example.com",
            full_name="Preserved User",
            role="manager",
            password_hash="hash",
        ))
        db.session.add(BootstrapState(bootstrap_complete=True))
        db.session.commit()

    recreated = create_app(config)
    with recreated.app_context():
        assert db.session.query(User).count() == 1
        preserved = db.session.query(User).filter_by(email="preserved@example.com").one()
        assert preserved.full_name == "Preserved User"
        bootstrap_state = db.session.query(BootstrapState).first()
        assert bootstrap_state is not None
        assert bootstrap_state.bootstrap_complete is True
