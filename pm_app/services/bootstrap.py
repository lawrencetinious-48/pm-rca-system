import os
import sys

from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from model import BootstrapState, User, db
from pm_app.auth.utils import hash_password


def _bootstrap_is_disabled():
    skip_bootstrap = os.getenv("SKIP_BOOTSTRAP", "").strip().lower()
    if skip_bootstrap in {"1", "true", "yes", "on"}:
        return True

    argv = sys.argv
    return "db" in argv and any(token in argv for token in {"upgrade", "revision", "downgrade", "stamp", "merge", "heads", "history", "current", "show"})


def _normalize_bootstrap_admin_name(app):
    configured_name = str(app.config.get("BOOTSTRAP_ADMIN_NAME") or os.getenv("BOOTSTRAP_ADMIN_NAME") or "System Administrator").strip()
    return configured_name or "System Administrator"


def _normalize_bootstrap_admin_email(app):
    configured_email = str(app.config.get("BOOTSTRAP_ADMIN_EMAIL") or os.getenv("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
    return configured_email


def _normalize_bootstrap_admin_password(app):
    configured_password = str(app.config.get("BOOTSTRAP_ADMIN_PASSWORD") or os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or "").strip()
    return configured_password


def _ensure_schema(app):
    inspector = inspect(db.engine)
    if inspector.has_table("users") and inspector.has_table("bootstrap_state"):
        return

    db.create_all()
    app.logger.info("Bootstrap schema initialized automatically.")


def _ensure_bootstrap_state(app, users_exist):
    bootstrap_state = BootstrapState.query.first()
    if bootstrap_state is None:
        bootstrap_state = BootstrapState(bootstrap_complete=users_exist)
        db.session.add(bootstrap_state)
        db.session.commit()
        app.logger.info("Created bootstrap_state row.")
        return bootstrap_state

    if users_exist and not bootstrap_state.bootstrap_complete:
        bootstrap_state.bootstrap_complete = True
        db.session.commit()
        app.logger.info("Marked bootstrap_state as complete because users already exist.")
    elif not users_exist and bootstrap_state.bootstrap_complete:
        bootstrap_state.bootstrap_complete = False
        db.session.commit()
        app.logger.info("Reset bootstrap_state to incomplete because no users exist.")

    return bootstrap_state


def _ensure_directories(app):
    upload_folder = app.config.get("UPLOAD_FOLDER")
    photo_folder = app.config.get("PHOTO_LIBRARY_FOLDER")

    for folder in (upload_folder, photo_folder, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "instance", "signatures")):
        if folder:
            os.makedirs(folder, exist_ok=True)


def _ensure_default_admin(app, bootstrap_state):
    admin_name = _normalize_bootstrap_admin_name(app)
    admin_email = _normalize_bootstrap_admin_email(app)
    admin_password = _normalize_bootstrap_admin_password(app)

    if not admin_email:
        return

    if not admin_password:
        app.logger.warning("BOOTSTRAP_ADMIN_EMAIL is set but BOOTSTRAP_ADMIN_PASSWORD is not configured; skipping default admin creation.")
        return

    existing_admin = User.query.filter_by(email=admin_email).first()
    if existing_admin:
        if existing_admin.role != "admin":
            existing_admin.role = "admin"
            db.session.commit()
            app.logger.info("Upgraded existing bootstrap admin email to admin role.")
        return

    first_name, last_name = "", ""
    name_parts = [part for part in admin_name.split() if part]
    if len(name_parts) >= 2:
        first_name = name_parts[0]
        last_name = " ".join(name_parts[1:])
    elif name_parts:
        first_name = name_parts[0]

    admin_user = User(
        email=admin_email,
        full_name=admin_name,
        first_name=first_name or None,
        last_name=last_name or None,
        password_hash=hash_password(admin_password),
        role="admin",
    )
    db.session.add(admin_user)
    if bootstrap_state:
        bootstrap_state.bootstrap_complete = True
        bootstrap_state.first_developer = admin_user
    db.session.commit()
    app.logger.info("Created bootstrap admin account for %s.", admin_email)


def initialize_system(app):
    if _bootstrap_is_disabled():
        app.logger.info("Skipping bootstrap initialization because migration tooling is running.")
        return

    with app.app_context():
        try:
            _ensure_schema(app)
            users_exist = User.query.count() > 0
            bootstrap_state = _ensure_bootstrap_state(app, users_exist)
            _ensure_directories(app)
            _ensure_default_admin(app, bootstrap_state)
        except OperationalError as exc:
            app.logger.warning("Skipping bootstrap initialization because the database is unavailable: %s", exc)
            return
