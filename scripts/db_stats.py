#!/usr/bin/env python3
"""
Print counts for key tables to verify clearing succeeded.
"""
import sys
sys.path.insert(0, '.')

from pm_app import create_app
from model import db, User, Activity, Consumable, BootstrapState


def main():
    app = create_app()
    with app.app_context():
        user_count = db.session.query(User).count()
        activity_count = db.session.query(Activity).count()
        consumable_count = db.session.query(Consumable).count()
        bs = db.session.query(BootstrapState).all()
        print(f"users={user_count}")
        print(f"activities={activity_count}")
        print(f"consumables={consumable_count}")
        print(f"bootstrap_state_rows={len(bs)}")
        if bs:
            print(f"bootstrap_complete={bs[0].bootstrap_complete}")

if __name__ == '__main__':
    main()
