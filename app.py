#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compatibility shim for tests: re-export selected helpers/constants from
the internal modules so `from app import ...` used in tests continues to
work.

This compatibility module is deprecated. Import `create_app` from
`pm_app` directly (e.g. `from pm_app import create_app`) in new code.
"""

import os
import warnings

from app_main import create_app

warnings.warn(
    "app.py is a legacy compatibility shim. Import create_app from pm_app directly in new code.",
    DeprecationWarning,
    stacklevel=2,
)

app = create_app()

# This compatibility shim remains for legacy imports and tests.
# New code should import `create_app` from `pm_app` directly.

# Re-export utilities and constants expected by tests
from pm_app.legacy_helpers import (
    normalize_public_base_url,
    _HOLIDAYS_CONFIG,
    get_public_holidays,
    HIGH_RISK_THRESHOLD,
    MEDIUM_RISK_THRESHOLD,
    SLA_DUE_SOON_HOURS,
    _check_image_magic,
    save_signature_image,
    is_public_share_base,
)
from pm_app.legacy_analysis import (
    analyze_outage_signals,
    classify_risk_level,
    derive_sla_suggestion,
    extract_recommendations_from_details,
    analyze_uploaded_photo_quality,
)

__all__ = [
    "create_app",
    "normalize_public_base_url",
    "_HOLIDAYS_CONFIG",
    "get_public_holidays",
    "HIGH_RISK_THRESHOLD",
    "MEDIUM_RISK_THRESHOLD",
    "SLA_DUE_SOON_HOURS",
    "_check_image_magic",
    "save_signature_image",
    "is_public_share_base",
    "analyze_outage_signals",
    "classify_risk_level",
    "derive_sla_suggestion",
    "extract_recommendations_from_details",
    "analyze_uploaded_photo_quality",
]

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", "8000"))
    app.logger.info(f"Starting Flask app on http://0.0.0.0:{port}")

    logout_routes = [rule for rule in app.url_map.iter_rules() if rule.rule in {"/logout", "/logout/"}]
    for rule in logout_routes:
        app.logger.info(f"Logout route registered: {rule.rule} methods={sorted(rule.methods or [])}")

    use_reloader = os.getenv("FLASK_USE_RELOADER", "0") == "1"
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        host="0.0.0.0",
        port=port,
        use_reloader=use_reloader,
    )
