#!/usr/bin/env python3
"""Factory reset for the local SQLite development database."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from pm_app import create_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def parse_sqlite_path(database_url):
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RuntimeError("reset_system.py currently supports sqlite only.")
    if parsed.netloc and parsed.netloc != "":
        raise RuntimeError("Unsupported sqlite URL format.")

    raw_path = parsed.path.lstrip("/")
    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def stamp_head():
    env = os.environ.copy()
    env["FLASK_APP"] = "app.py"
    env["SKIP_BOOTSTRAP"] = "1"
    result = subprocess.run([sys.executable, "-m", "flask", "db", "stamp", "head"], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError("flask db stamp head failed.")


def main():
    database_url = os.getenv("DATABASE_URL") or os.getenv("DEV_DATABASE_URL") or "sqlite:///instance/dev_pm.sqlite"
    sqlite_path = parse_sqlite_path(database_url)

    if sqlite_path.exists():
        sqlite_path.unlink()

    create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "RESET_DEV_DB_ON_START": False,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{sqlite_path}",
        }
    )

    stamp_head()

    print(f"Database reset complete: {sqlite_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
