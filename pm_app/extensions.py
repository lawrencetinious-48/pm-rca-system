from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pm_app import login_manager


def init_extensions(app, *, redis_client=None):
    """Initialize and attach shared extensions to the Flask app.

    Returns a dict of instantiated extensions for callers that need them.
    """
    limiter_storage = None
    if redis_client is not None:
        limiter_storage = getattr(redis_client, 'url', None) or app.config.get('REDIS_URL')
    if not limiter_storage:
        limiter_storage = "memory://"

    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        storage_uri=limiter_storage,
        default_limits=["600 per minute"],
        headers_enabled=True,
    )

    # Configure the shared login manager from pm_app
    login_manager.init_app(app)
    setattr(login_manager, "login_view", "login")

    return {
        "limiter": limiter,
        "login_manager": login_manager,
    }
