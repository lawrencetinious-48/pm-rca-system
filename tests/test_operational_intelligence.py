import os
from pathlib import Path

from model import AuditLog, BootstrapState, User, db
from pm_app import create_app


def test_system_status_includes_audit_history(tmp_path):
    db_path = tmp_path / "ops.sqlite"
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
        user = User(
            email="ops@example.com",
            full_name="Ops User",
            password_hash="hash",
            role="developer",
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(BootstrapState(bootstrap_complete=True, first_developer_id=user.id))
        AuditLog.log("system_boot", "system", user=user, details={"phase": "startup"})
        AuditLog.log("audit_snapshot", "system", user=user, details={"phase": "status"})
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user.id)

        response = client.get("/system-status")

    assert response.status_code in {200, 503}
    payload = response.get_json()
    assert payload["audit_history"]["total_events"] >= 2
    assert payload["audit_history"]["window_hours"] == 24
    assert len(payload["audit_history"]["recent_events"]) == 2
    assert payload["audit_history"]["recent_events"][0]["action"] == "audit_snapshot"
