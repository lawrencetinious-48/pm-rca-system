from model import BootstrapState, User
from pm_app import create_app

import maintenance.system_audit as system_audit


def test_repair_bootstrap_creates_missing_admin(tmp_path, monkeypatch):
    db_path = tmp_path / "repair_bootstrap.sqlite"
    monkeypatch.delenv("BOOTSTRAP_ADMIN_NAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)

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
        assert User.query.filter_by(role="admin").first() is None

    monkeypatch.setenv("BOOTSTRAP_ADMIN_NAME", "Repair Admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "repair@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "StrongPass123!")

    repair_info = system_audit.repair_bootstrap(app)

    assert repair_info["attempted"] is True
    assert repair_info["created_admin"] is True
    assert repair_info["bootstrap_complete"] is True

    with app.app_context():
        admin = User.query.filter_by(email="repair@example.com").first()
        bootstrap_state = BootstrapState.query.first()

    assert admin is not None
    assert admin.role == "admin"
    assert admin.full_name == "Repair Admin"
    assert bootstrap_state is not None
    assert bootstrap_state.bootstrap_complete is True
    assert bootstrap_state.first_developer_id == admin.id
