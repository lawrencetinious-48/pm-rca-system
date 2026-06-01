#!/usr/bin/env python3
"""Reset password for an existing user."""

import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse
import os

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pm_app.auth.utils import hash_password

PROJECT_ROOT = Path(__file__).resolve().parent

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
    return path

def main():
    email = "staff@example.com"
    new_password = "StaffPassword123!"
    
    database_url = os.getenv("DATABASE_URL") or "sqlite:///tmp_test_pm.sqlite"
    sqlite_path = _resolve_sqlite_path(database_url)
    
    if sqlite_path is None:
        print("Could not resolve database path")
        return 1
    
    conn = sqlite3.connect(sqlite_path)
    try:
        # Check if user exists
        user = conn.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            print(f"User {email} not found")
            return 1
        
        # Update password
        password_hash = hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (password_hash, email))
        conn.commit()
        
        print(f"✅ Password reset successfully for {email}")
        print(f"   New password: {new_password}")
        
    finally:
        conn.close()
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
