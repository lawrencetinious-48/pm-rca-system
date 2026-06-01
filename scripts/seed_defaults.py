#!/usr/bin/env python3
"""Seed required bootstrap defaults for a clean local or test database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pm_app import create_app
from pm_app.services.bootstrap import initialize_system


def main():
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "RESET_DEV_DB_ON_START": False,
            "SECRET_KEY": "test-secret-key",
        }
    )

    with app.app_context():
        initialize_system(app)

    print("Bootstrap defaults applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
