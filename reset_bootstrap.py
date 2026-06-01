#!/usr/bin/env python3
"""Reset bootstrap to allow fresh onboarding flow."""

from pm_app import create_app
from model import db, BootstrapState, User

app = create_app()

with app.app_context():
    try:
        # Delete all users to start fresh
        User.query.delete()
        db.session.commit()
        print("✅ Cleared all users")
        
        # Reset bootstrap state
        BootstrapState.query.delete()
        bootstrap = BootstrapState(bootstrap_complete=False, first_developer_id=None)
        db.session.add(bootstrap)
        db.session.commit()
        print("✅ Bootstrap reset - ready for fresh onboarding flow")
        print("\nGo to http://localhost:8000 to start from terms & conditions")
        
    except Exception as e:
        print(f"Error: {e}")
        db.session.rollback()
