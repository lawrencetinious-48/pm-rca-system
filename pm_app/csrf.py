import secrets
import hmac
from flask import session, request


def get_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_token_is_valid():
    expected = session.get("csrf_token", "")
    if not expected:
        return False

    provided = (
        request.form.get("csrf_token")
        or request.form.get("login_csrf_token")
        or request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()

    if not provided and request.is_json:
        payload = request.get_json(silent=True) or {}
        provided = (payload.get("csrf_token") or "").strip()

    return bool(provided) and hmac.compare_digest(expected, provided)


class CsrfToken:
    """Callable/printable wrapper so templates can use either
    `{{ csrf_token }}` or `{{ csrf_token() }}` interchangeably.
    """
    def __call__(self):
        return get_csrf_token()

    def __str__(self):
        return get_csrf_token()
