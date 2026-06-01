import pytest

from pm_app.legacy_app import create_app


def test_create_app_production_requires_postgres_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEV_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required in production"):
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            }
        )


def test_create_app_production_requires_strong_secret_key():
    with pytest.raises(RuntimeError, match="Production requires a strong SECRET_KEY"):
        create_app(
            {
                "APP_ENV": "production",
                "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://pm_user:password@localhost:5432/pm_db",
                "SECRET_KEY": "weaksecret",
                "SESSION_COOKIE_SECURE": "1",
            }
        )


def test_create_app_production_defaults_secure_cookie_and_https_scheme():
    app = create_app(
        {
            "APP_ENV": "production",
            "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://pm_user:password@localhost:5432/pm_db",
            "SECRET_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "SESSION_COOKIE_SECURE": "1",
            "PUBLIC_BASE_URL": "https://pm.example.com",
        }
    )

    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_SECURE"] is True
    assert app.config["PREFERRED_URL_SCHEME"] == "https"
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://")


def test_create_app_production_requires_real_public_base_url():
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        create_app(
            {
                "APP_ENV": "production",
                "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://pm_user:password@localhost:5432/pm_db",
                "SECRET_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "SESSION_COOKIE_SECURE": "1",
                "PUBLIC_BASE_URL": "https://your-production-domain.example",
            }
        )


def test_create_app_production_reports_all_config_errors():
    with pytest.raises(RuntimeError) as exc_info:
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "weaksecret",
                "SESSION_COOKIE_SECURE": "0",
                "PUBLIC_BASE_URL": "https://your-production-domain.example",
            }
        )

    message = str(exc_info.value)
    assert "DATABASE_URL is required in production" in message
    assert "Production requires a strong SECRET_KEY" in message
    assert "Production requires secure cookies" in message
    assert "PUBLIC_BASE_URL" in message


def test_create_app_production_reports_runtime_validation_errors():
    with pytest.raises(RuntimeError) as exc_info:
        create_app(
            {
                "APP_ENV": "production",
                "RUN_RUNTIME_VALIDATION": True,
                "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://127.0.0.1:1/pm_db",
                "SECRET_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "SESSION_COOKIE_SECURE": "1",
                "PUBLIC_BASE_URL": "https://pm.example.com",
                "REDIS_URL": "redis://127.0.0.1:1/0",
                "ALERT_SMTP_HOST": "127.0.0.1",
                "ALERT_SMTP_PORT": "1",
                "ALERT_SMTP_USE_SSL": "1",
                "ALERT_SMTP_USE_TLS": "0",
            }
        )

    message = str(exc_info.value)
    assert "Production runtime validation errors" in message
    assert "Database reachability check failed" in message
    assert "Redis reachability check failed" in message
    assert "SMTP reachability check failed" in message
