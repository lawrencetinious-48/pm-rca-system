#!/usr/bin/env python3
"""
Create the first developer/admin user for a fresh production deployment.

Usage:
  python scripts/create_admin.py --email admin@example.com --name "Admin User" --password "StrongPass123!"

This script is safer than relying on the self-service endpoint and works when no developer account exists.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pm_app import create_app
from pm_app.auth.utils import hash_password

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args():
    parser = argparse.ArgumentParser(description="Create a first developer/admin account")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--name", required=True, help="Full name of the admin")
    parser.add_argument("--password", required=True, help="Password for the admin account")
    parser.add_argument("--role", default="admin", help="Role for the admin account (default: admin)")
    return parser.parse_args()


def _resolve_sqlite_path(database_url):
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        return None

    raw_path = parsed.path.lstrip("/")
    if not raw_path:
        return None

    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_sqlite_database(sqlite_path):
    create_app(
        test_config={
            "APP_ENV": os.getenv("APP_ENV", "development"),
            "SECRET_KEY": os.getenv("SECRET_KEY", "test-secret-key"),
            "RESET_DEV_DB_ON_START": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{sqlite_path.as_posix()}",
        }
    )


def _load_existing_user_count(conn):
    row = conn.execute("SELECT COUNT(*) AS user_count FROM users").fetchone()
    return int(row[0]) if row else 0


def _load_existing_email(conn, email):
    row = conn.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
    return row


def _create_admin_record(conn, email, full_name, password_hash, role):
    cur = conn.execute(
        """
        INSERT INTO users (email, password_hash, full_name, role, is_blocked, created_at)
        VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        """,
        (email, password_hash, full_name, role),
    )
    return int(cur.lastrowid)


def _upsert_bootstrap_state(conn, user_id):
    existing = conn.execute("SELECT id FROM bootstrap_state LIMIT 1").fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO bootstrap_state (bootstrap_complete, first_developer_id, completed_at, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (1, user_id),
        )
        return

    conn.execute(
        """
        UPDATE bootstrap_state
        SET bootstrap_complete = 1,
            first_developer_id = ?,
            completed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (user_id, existing[0]),
    )


def main():
    args = parse_args()

    if len(args.password) < 8:
        print("Password must be at least 8 characters long.")
        return 1

    database_url = os.getenv("DATABASE_URL") or os.getenv("DEV_DATABASE_URL") or "sqlite:///instance/dev_pm.sqlite"
    sqlite_path = _resolve_sqlite_path(database_url)

    if sqlite_path is None:
        print("This script currently supports SQLite databases directly. Use a SQLite DATABASE_URL or DEV_DATABASE_URL.")
        return 1

    _prepare_sqlite_database(sqlite_path)

    conn = sqlite3.connect(sqlite_path)
    try:
        existing_user_count = _load_existing_user_count(conn)
        if existing_user_count > 0:
            existing_user = conn.execute("SELECT email FROM users LIMIT 1").fetchone()
            print("A user account already exists. Aborting to avoid duplicate bootstrap.")
            print(f"Existing user: {existing_user[0]}")
            return 1

        existing_email = _load_existing_email(conn, args.email.lower())
        if existing_email:
            print("A user with this email already exists. Choose another email or delete the existing user.")
            return 1

        password_hash = hash_password(args.password)
        user_id = _create_admin_record(conn, args.email.lower(), args.name, password_hash, args.role)
        _upsert_bootstrap_state(conn, user_id)
        conn.commit()
    finally:
        conn.close()

    print("Admin account created successfully:")
    print(f"  Email: {args.email.lower()}")
    print(f"  Role: {args.role}")
    print("You can now log in with this account.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
