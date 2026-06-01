#!/usr/bin/env python3
"""
Backup the configured database before destructive operations.
Supports SQLite (copy file) and PostgreSQL (pg_dump if available).
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, '.')
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')
load_dotenv(PROJECT_ROOT / '.env.prod')

DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('DEV_DATABASE_URL')

OUT_DIR = PROJECT_ROOT / 'backups'
OUT_DIR.mkdir(exist_ok=True)


def backup_sqlite(path):
    src = Path(path)
    if not src.exists():
        print(f"SQLite DB not found at {src}")
        return 1
    dest = OUT_DIR / (src.name + '.' + str(int(Path().stat().st_mtime if Path().exists() else 0)))
    shutil.copy2(src, dest)
    print(f"Copied SQLite DB to {dest}")
    return 0


def backup_postgres(url):
    # Use pg_dump if available
    pg_dump = shutil.which('pg_dump')
    if not pg_dump:
        print('pg_dump not found on PATH — cannot create Postgres dump. Install pg_dump or use pg_dump in host.')
        return 2
    dest = OUT_DIR / f"postgres_dump_{int(os.times().system)}.sql"
    cmd = [pg_dump, url, '-F', 'p']
    try:
        with open(dest, 'wb') as f:
            subprocess.check_call(cmd, stdout=f)
        print(f"Postgres dump saved to {dest}")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"pg_dump failed: {e}")
        return 3


def main():
    if not DATABASE_URL:
        print("No DATABASE_URL configured in env; aborting backup.")
        return 1
    if DATABASE_URL.startswith('sqlite'):
        # format sqlite:///path/to/file
        path = DATABASE_URL.replace('sqlite:///', '')
        return backup_sqlite(path)
    elif DATABASE_URL.startswith('postgres') or DATABASE_URL.startswith('postgresql'):
        return backup_postgres(DATABASE_URL)
    else:
        print(f"Unsupported DATABASE_URL scheme: {DATABASE_URL}")
        return 4


if __name__ == '__main__':
    sys.exit(main())
