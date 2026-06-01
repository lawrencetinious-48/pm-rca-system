from functools import wraps
from flask import abort
from pm_app import login_manager
from model import db, User
from app_pkg.utils import is_admin_role, is_desk_role


@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
    except Exception:
        return None
    if user and getattr(user, "is_blocked", False):
        return None
    return user


def manager_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        from flask_login import current_user

        if not current_user.is_authenticated or not is_admin_role(current_user.role):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def desk_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        from flask_login import current_user

        if not current_user.is_authenticated or not is_desk_role(current_user.role):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def developer_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        from flask_login import current_user

        if not current_user.is_authenticated or current_user.role not in {"developer", "admin"}:
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped
