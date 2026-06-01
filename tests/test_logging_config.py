import logging
from pathlib import Path

from logging.handlers import RotatingFileHandler

import pm_app.legacy_app as legacy_app
from pm_app.legacy_app import create_app


def test_logging_uses_non_rotating_file_handler():
    app = create_app({"TESTING": True})

    file_handlers = [handler for handler in app.logger.handlers if isinstance(handler, logging.FileHandler)]
    rotating_handlers = [handler for handler in app.logger.handlers if isinstance(handler, RotatingFileHandler)]

    assert file_handlers, "expected a file handler to be configured"
    assert not rotating_handlers, "expected logging to avoid RotatingFileHandler on Windows"


def test_redis_unavailable_logs_as_warning_in_development(caplog):
    logger = logging.getLogger("redis-log-dev")

    with caplog.at_level(logging.WARNING, logger="redis-log-dev"):
        try:
            raise RuntimeError("redis down")
        except Exception:
            legacy_app._log_redis_unavailable(logger, "development")

    assert "Redis unavailable. Falling back to in-memory throttling." in caplog.text
    assert "Traceback" not in caplog.text


def test_redis_unavailable_logs_exception_in_production(caplog):
    logger = logging.getLogger("redis-log-prod")

    with caplog.at_level(logging.ERROR, logger="redis-log-prod"):
        try:
            raise RuntimeError("redis down")
        except Exception:
            legacy_app._log_redis_unavailable(logger, "production")

    assert "Redis unavailable. Falling back to in-memory throttling." in caplog.text
    assert "Traceback" in caplog.text


def test_redis_unavailable_logs_as_warning_in_development_startup():
    log_path = Path("pm_app/logs/app.log")
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    create_app(
        {
            "TESTING": False,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "REDIS_URL": "redis://invalid-host.local:6379/0",
        }
    )

    log_text = log_path.read_text(encoding="utf-8")

    assert "WARNING | Redis unavailable. Falling back to in-memory throttling." in log_text
    assert "INFO | Redis unavailable" not in log_text
