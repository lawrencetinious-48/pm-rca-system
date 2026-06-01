import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from model import User, db
from pm_app import create_app


def test_validate_backup_script_accepts_sqlite_backup(tmp_path):
    db_path = tmp_path / "recovery.sqlite"
    backup_path = tmp_path / "recovery.sqlite.bak"
    project_root = Path(__file__).resolve().parents[1]

    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "REDIS_URL": "redis://localhost:6379/0",
        }
    )

    with app.app_context():
        db.create_all()
        db.session.add(
            User(
                email="recovery@example.com",
                full_name="Recovery User",
                password_hash="hash",
                role="admin",
            )
        )
        db.session.commit()

    shutil.copy2(db_path, backup_path)

    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{db_path}",
            "DEV_DATABASE_URL": f"sqlite:///{db_path}",
        }
    )

    result = subprocess.run(
        [sys.executable, "scripts/validate_backup.py", "--backup", str(backup_path)],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert '"backup_ok": true' in result.stdout

    with sqlite3.connect(backup_path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    assert integrity == "ok"
    assert user_count == 1
