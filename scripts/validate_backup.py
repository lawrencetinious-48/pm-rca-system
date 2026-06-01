#!/usr/bin/env python3
"""Validate a database backup and verify it can be restored cleanly."""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.prod")


REQUIRED_TABLES = {"users", "bootstrap_state", "audit_logs"}


def _load_database_url() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("DEV_DATABASE_URL") or ""


def _extract_sqlite_path(database_url: str) -> Path | None:
    if not database_url:
        return None
    if not database_url.startswith("sqlite"):
        return None

    candidate = database_url
    if candidate.startswith("sqlite:///"):
        candidate = candidate[len("sqlite:///") :]
    elif candidate.startswith("sqlite://"):
        candidate = candidate[len("sqlite://") :]

    if candidate.startswith("/"):
        candidate = candidate[1:]
    return Path(candidate)


def _inspect_sqlite(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return {
            "integrity": integrity[0] if integrity else "unknown",
            "tables": sorted(tables),
            "user_count": int(user_count),
        }
    finally:
        conn.close()


def _find_latest_backup() -> Path | None:
    backup_dir = PROJECT_ROOT / "backups"
    if not backup_dir.exists():
        return None

    candidates = [path for path in backup_dir.iterdir() if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _validate_backup(backup_path: Path, source_path: Path | None) -> dict:
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    with tempfile.TemporaryDirectory() as temp_dir:
        restored_path = Path(temp_dir) / backup_path.name
        shutil.copy2(backup_path, restored_path)
        restored_info = _inspect_sqlite(restored_path)

        source_info = None
        if source_path and source_path.exists():
            source_info = _inspect_sqlite(source_path)

        missing_tables = sorted(REQUIRED_TABLES - set(restored_info["tables"]))
        backup_ok = restored_info["integrity"] == "ok" and not missing_tables
        source_matches = None
        if source_info is not None:
            source_matches = (
                source_info["integrity"] == restored_info["integrity"]
                and source_info["tables"] == restored_info["tables"]
                and source_info["user_count"] == restored_info["user_count"]
            )

        return {
            "backup_ok": backup_ok,
            "backup_path": str(backup_path),
            "restored_ok": backup_ok,
            "integrity": restored_info["integrity"],
            "tables": restored_info["tables"],
            "user_count": restored_info["user_count"],
            "missing_tables": missing_tables,
            "source_matches": source_matches,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", type=Path, help="Path to the backup file to validate")
    args = parser.parse_args()

    backup_path = args.backup or _find_latest_backup()
    if backup_path is None:
        print(json.dumps({"error": "no_backup_found", "backup_ok": False}, indent=2))
        return 2

    source_path = _extract_sqlite_path(_load_database_url())

    try:
        result = _validate_backup(backup_path, source_path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["backup_ok"] else 1
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc), "backup_ok": False}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
