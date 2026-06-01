#!/usr/bin/env python3
"""
Clear all user data and application data rows from the database while preserving schema/migrations.
THIS IS DESTRUCTIVE: requires explicit confirmation via --confirm flag.

Usage:
  python scripts/clear_db.py --confirm

The script will:
- Backup DB to backups/
- Truncate (Postgres) or DELETE (SQLite) all user-data tables except `alembic_version`.
- Reset Postgres sequences where applicable.
- Recreate a default bootstrap_state row with bootstrap_complete=false.
"""
import os
import sys
import argparse
from pathlib import Path

sys.path.insert(0, '.')
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')
load_dotenv(PROJECT_ROOT / '.env.prod')

from pm_app import create_app
from model import db, BootstrapState
from sqlalchemy import text


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--confirm', action='store_true', help='Confirm destructive action')
    return p.parse_args()


def backup():
    print('Backing up DB...')
    rc = os.system(f'python "{PROJECT_ROOT / "scripts" / "db_backup.py"}"')
    if rc != 0:
        print('Backup script returned non-zero code; aborting.')
        return False
    return True


def clear_all(app):
    # Ensure we operate with an application context
    with app.app_context():
        engine = db.engine
        conn = engine.connect()

        meta = db.metadata
        # Load table list from metadata but only include tables present in DB
        from sqlalchemy import inspect
        inspector = inspect(engine)
        existing_table_names = set(inspector.get_table_names())
        # Load table list
        tables = [t for t in meta.sorted_tables if t.name in existing_table_names]
        # Exclude alembic_version
        skip = {'alembic_version'}

        trans = conn.begin()
        try:
            if engine.dialect.name == 'postgresql':
                tbl_names = [t.name for t in tables if t.name not in skip]
                if tbl_names:
                    sql = 'TRUNCATE TABLE ' + ','.join([f'"{n}"' for n in tbl_names]) + ' RESTART IDENTITY CASCADE;'
                    conn.execute(text(sql))
                # Reset sequences handled by RESTART IDENTITY
            else:
                # SQLite or others: delete rows
                for t in reversed(tables):
                    if t.name in skip:
                        continue
                    conn.execute(t.delete())
            trans.commit()
        except Exception:
            trans.rollback()
            raise

    # Ensure bootstrap_state row exists with bootstrap_complete = false
    with app.app_context():
        db.session.query(BootstrapState).delete()
        bs = BootstrapState(bootstrap_complete=False)
        db.session.add(bs)
        db.session.commit()


def main():
    args = parse_args()
    if not args.confirm:
        print('This is destructive. Re-run with --confirm to proceed.')
        return 2
    if not backup():
        return 3

    app = create_app()
    print('Clearing DB data...')
    clear_all(app)
    print('Database cleared. A new empty bootstrap_state row has been created.')
    print('Please verify backups/ and then restart your services.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
