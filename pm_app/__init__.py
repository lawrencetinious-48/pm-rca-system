"""
PM/RCA application package.

This module provides a compatibility app factory that delegates to the
legacy monolithic app.py factory. It is the entrypoint for the ongoing
modularisation effort.
"""

from __future__ import annotations

from typing import Optional
from flask_login import LoginManager

# Global login manager instance (configured by the legacy app)
login_manager = LoginManager()

# Celery instance (configured in pm_app.celery)
from pm_app.celery import celery as celery_app, init_celery as init_celery_app

__all__ = ["celery_app", "init_celery_app"]


def create_app(config_class: Optional[str] = None, test_config: Optional[dict] = None):
    """Compatibility app factory that delegates to the legacy factory.

    This package is the modular entrypoint for the ongoing split. Route logic
    remains in the legacy factory until extraction is complete.

    Args:
        config_class: Optional dotted path to a config class (unused currently).
        test_config: Optional test configuration dict (passed to legacy factory).

    Returns:
        A configured Flask application instance.
    """
    if isinstance(config_class, dict) and test_config is None:
        test_config = config_class
        config_class = None

    # Defer import to avoid circular dependency
    from pm_app.legacy_app import create_app as legacy_create_app

    app = legacy_create_app(test_config=test_config)

    # Initialize Celery with app
    from pm_app.celery import init_celery
    init_celery(app)

    # Keep optional config_class support for future module-native config.
    if config_class:
        app.config.from_object(config_class)

    return app
