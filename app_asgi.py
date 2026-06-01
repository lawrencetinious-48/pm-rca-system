"""
ASGI entry point for the PM/RCA application.
Wraps the Flask WSGI app using `asgiref` to run under ASGI servers (e.g., Uvicorn, Daphne).
"""

import os
import logging
from asgiref.wsgi import WsgiToAsgi

from app import create_app

# Configure logging for ASGI startup (can be overridden by app config)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("asgi")

# Optional test configuration (e.g., for testing ASGI under pytest)
test_config = None
if os.getenv("FLASK_ENV") == "testing" or os.getenv("TESTING") == "1":
    test_config = {"TESTING": True}
    logger.info("Running ASGI app in TESTING mode")

# Create the Flask application instance
try:
    flask_app = create_app(test_config=test_config)
    logger.info("Flask app created successfully")
except Exception:
    logger.exception("Failed to create Flask app")
    raise

# Wrap WSGI app to ASGI
asgi_app = WsgiToAsgi(flask_app)
logger.info("ASGI wrapper ready")

# For running directly with Uvicorn (optional):
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info(f"Starting ASGI server on {host}:{port}")
    uvicorn.run(asgi_app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())
