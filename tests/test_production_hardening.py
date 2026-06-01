import pytest

from pm_app import create_app


def test_create_app_fails_in_production_when_bootstrap_integrity_is_unhealthy(tmp_path):
    db_path = tmp_path / "production_integrity.sqlite"

    with pytest.raises(RuntimeError, match="Critical system integrity failure"):
        create_app(
            {
                "TESTING": True,
                "APP_ENV": "production",
                "SECRET_KEY": "superlongdevelopmentsecretkey1234567890",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
                "REDIS_URL": "redis://localhost:6379/0",
                "SESSION_COOKIE_SECURE": True,
            }
        )


def test_system_status_requires_authentication(tmp_path):
    db_path = tmp_path / "system_status.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SECRET_KEY": "superlongdevelopmentsecretkey1234567890",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "REDIS_URL": "redis://localhost:6379/0",
        }
    )

    response = app.test_client().get("/system-status")

    assert response.status_code == 302
