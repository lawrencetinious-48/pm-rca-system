from flask import Blueprint

bp = Blueprint("activities", __name__)


def register_activity_routes(app, create_activity=None):
    """Register minimal activity routes used by tests.

    When the blueprint has already been registered the app will raise an
    AssertionError if we attempt to call `bp.route` afterwards. To support
    both registration orders we add lightweight rules directly to the app
    when the blueprint is already registered.
    """

    def _health():
        return "ok"

    # If blueprint has not yet been registered, attach route to blueprint
    try:
        bp.add_url_rule("/health", endpoint="activities.health", view_func=_health)
    except AssertionError:
        # Blueprint was already registered; register the rule on the app instead
        app.add_url_rule("/health", endpoint="activities.health", view_func=_health)


def register_activity_app_handlers(app):
    """Placeholder for registering app-level handlers referenced by legacy code."""
    return None
