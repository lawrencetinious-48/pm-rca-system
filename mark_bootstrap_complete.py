#!/usr/bin/env python3
"""Mark bootstrap as complete."""

from pm_app import create_app
from model import db, BootstrapState

app = create_app()

with app.app_context():
    try:
        # Check if bootstrap_state exists
        bootstrap = BootstrapState.query.first()
        if bootstrap:
            bootstrap.bootstrap_complete = True
            db.session.commit()
            print("✅ Bootstrap marked as complete")
        else:
            print("⚠️ No bootstrap state found, creating one...")
            bootstrap = BootstrapState(bootstrap_complete=True, first_developer_id=1)
            db.session.add(bootstrap)
            db.session.commit()
            print("✅ Bootstrap state created and marked complete")
    except Exception as e:
        print(f"Error: {e}")
        db.session.rollback()
